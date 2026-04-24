"""FastAPI entry point — SentimentTools v3.0."""
import asyncio, csv, io, json, logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select, func, delete

from src.config import settings
from src.database import init_db, async_session
from src.models import Job, SentimentResult as ResultORM
from src.tasks.progress import tracker
from src.tasks.orchestrator import (
    run_analysis_job, run_keyword_job, run_text_job,
    run_social_job, run_news_job,
)

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "exports").mkdir(exist_ok=True)
    (settings.data_dir / "logs").mkdir(exist_ok=True)
    await init_db()
    logger.info("Siap di http://%s:%s", settings.app_host, settings.app_port)
    yield
    logger.info("Shutdown")


app = FastAPI(title="SentimentTools", version="3.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="src/templates")


# ── Request / Response models ────────────────────────────────────────

class AnalysisReq(BaseModel):
    urls: list[str]
    depth: int = 2
    use_js_rendering: bool = False

class KeywordReq(BaseModel):
    keyword: str
    max_results: int = 10
    engine: str = "duckduckgo"
    site_filter: str | None = None
    depth: int = 0

class TextReq(BaseModel):
    texts: list[str]

class SocialReq(BaseModel):
    platform: str  # twitter, reddit, youtube, threads
    query: str
    max_results: int = 50
    subreddit: str | None = None
    include_comments: bool = False

class NewsReq(BaseModel):
    keyword: str | None = None
    sources: list[str] | None = None
    feed_url: str | None = None
    max_articles: int = 20

class JobResp(BaseModel):
    job_id: str
    status: str
    redirect_url: str


# ── Pages ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/job/{jid}", response_class=HTMLResponse)
async def job_page(request: Request, jid: str):
    st = tracker.get_state(jid)
    if not st:
        raise HTTPException(404)
    return templates.TemplateResponse("job.html", {"request": request, "job_id": jid, "initial_state": st})


@app.get("/results/{jid}", response_class=HTMLResponse)
async def results_page(request: Request, jid: str):
    async with async_session() as s:
        job = await s.get(Job, jid)
        if not job:
            raise HTTPException(404)
        stmt = (
            select(ResultORM.sentiment, func.count(ResultORM.id), func.avg(ResultORM.confidence))
            .where(ResultORM.job_id == jid)
            .group_by(ResultORM.sentiment)
        )
        rows = (await s.execute(stmt)).all()
        summary = {r[0]: {"count": r[1], "avg_confidence": round(r[2], 3) if r[2] else 0} for r in rows}
        total = (await s.execute(select(func.count(ResultORM.id)).where(ResultORM.job_id == jid))).scalar() or 0
        results = (
            await s.execute(select(ResultORM).where(ResultORM.job_id == jid).order_by(ResultORM.analyzed_at.desc()))
        ).scalars().all()
    return templates.TemplateResponse("results.html", {
        "request": request, "job_id": jid, "job": job,
        "summary": summary, "total": total, "results": results,
    })


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    async with async_session() as s:
        jobs = (await s.execute(
            select(Job).order_by(Job.created_at.desc()).limit(100)
        )).scalars().all()
    return templates.TemplateResponse("history.html", {"request": request, "jobs": jobs})


# ── API: Analysis ────────────────────────────────────────────────────

@app.post("/api/v1/analysis", response_model=JobResp)
async def create_analysis(req: AnalysisReq):
    if not req.urls:
        raise HTTPException(400, "Min 1 URL")
    valid = [u.strip() for u in req.urls if u.strip().startswith("http")]
    if not valid:
        raise HTTPException(400, "No valid URL")
    jid = str(uuid4())
    async with async_session() as s:
        s.add(Job(id=jid, status="QUEUED", input_type="url", source_type="web",
                   input_data={"urls": valid}, config={"depth": req.depth},
                   started_at=datetime.now(timezone.utc)))
        await s.commit()
    await tracker.create_job(jid, len(valid) * 3)
    asyncio.create_task(run_analysis_job(
        job_id=jid, urls=valid,
        max_depth=req.depth if req.depth != 2 else None,
        db_session_factory=async_session,
    ))
    return JobResp(job_id=jid, status="QUEUED", redirect_url=f"/job/{jid}")


@app.post("/api/v1/keyword", response_model=JobResp)
async def create_keyword_analysis(req: KeywordReq):
    if not req.keyword.strip():
        raise HTTPException(400, "Keyword required")
    jid = str(uuid4())
    async with async_session() as s:
        s.add(Job(id=jid, status="QUEUED", input_type="keyword", source_type="web",
                   keyword=req.keyword, input_data={"keyword": req.keyword},
                   config={"max_results": req.max_results, "engine": req.engine, "depth": req.depth},
                   started_at=datetime.now(timezone.utc)))
        await s.commit()
    await tracker.create_job(jid, req.max_results * 3)
    asyncio.create_task(run_keyword_job(
        job_id=jid, keyword=req.keyword, max_results=req.max_results,
        engine=req.engine, site_filter=req.site_filter, max_depth=req.depth,
        db_session_factory=async_session,
    ))
    return JobResp(job_id=jid, status="QUEUED", redirect_url=f"/job/{jid}")


@app.post("/api/v1/text", response_model=JobResp)
async def create_text_analysis(req: TextReq):
    valid = [t.strip() for t in req.texts if t.strip() and len(t.strip()) >= 10]
    if not valid:
        raise HTTPException(400, "Min 1 text (>= 10 chars)")
    jid = str(uuid4())
    async with async_session() as s:
        s.add(Job(id=jid, status="QUEUED", input_type="text", source_type="text",
                   input_data={"texts": valid[:500]}, config={},
                   started_at=datetime.now(timezone.utc)))
        await s.commit()
    await tracker.create_job(jid, len(valid))
    asyncio.create_task(run_text_job(job_id=jid, texts=valid, db_session_factory=async_session))
    return JobResp(job_id=jid, status="QUEUED", redirect_url=f"/job/{jid}")


@app.post("/api/v1/social", response_model=JobResp)
async def create_social_analysis(req: SocialReq):
    if req.platform not in ("twitter", "reddit", "youtube", "threads"):
        raise HTTPException(400, "Platform: twitter, reddit, youtube, threads")
    if not req.query.strip():
        raise HTTPException(400, "Query required")
    jid = str(uuid4())
    async with async_session() as s:
        s.add(Job(id=jid, status="QUEUED", input_type="social", source_type=req.platform,
                   keyword=req.query, input_data={"platform": req.platform, "query": req.query},
                   config={"max_results": req.max_results},
                   started_at=datetime.now(timezone.utc)))
        await s.commit()
    await tracker.create_job(jid, req.max_results)
    asyncio.create_task(run_social_job(
        job_id=jid, platform=req.platform, query=req.query,
        max_results=req.max_results, db_session_factory=async_session,
        subreddit=req.subreddit, include_comments=req.include_comments
    ))
    return JobResp(job_id=jid, status="QUEUED", redirect_url=f"/job/{jid}")


@app.post("/api/v1/news", response_model=JobResp)
async def create_news_analysis(req: NewsReq):
    jid = str(uuid4())
    async with async_session() as s:
        s.add(Job(id=jid, status="QUEUED", input_type="news", source_type="news",
                   keyword=req.keyword, input_data={"keyword": req.keyword, "sources": req.sources},
                   config={"max_articles": req.max_articles},
                   started_at=datetime.now(timezone.utc)))
        await s.commit()
    await tracker.create_job(jid, req.max_articles * 2)
    asyncio.create_task(run_news_job(
        job_id=jid, keyword=req.keyword, sources=req.sources,
        feed_url=req.feed_url, max_articles=req.max_articles,
        db_session_factory=async_session,
    ))
    return JobResp(job_id=jid, status="QUEUED", redirect_url=f"/job/{jid}")


@app.post("/api/v1/batch", response_model=JobResp)
async def create_batch_analysis(file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8", errors="ignore")
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    if not lines:
        raise HTTPException(400, "File is empty")
    urls = [l for l in lines if l.startswith("http")]
    texts = [l for l in lines if not l.startswith("http") and len(l) >= 10]
    jid = str(uuid4())
    if urls:
        async with async_session() as s:
            s.add(Job(id=jid, status="QUEUED", input_type="batch", source_type="web",
                       input_data={"urls": urls}, config={"depth": 1},
                       started_at=datetime.now(timezone.utc)))
            await s.commit()
        asyncio.create_task(run_analysis_job(job_id=jid, urls=urls, max_depth=1, db_session_factory=async_session))
    elif texts:
        async with async_session() as s:
            s.add(Job(id=jid, status="QUEUED", input_type="batch", source_type="text",
                       input_data={"texts": texts[:500]}, config={},
                       started_at=datetime.now(timezone.utc)))
            await s.commit()
        asyncio.create_task(run_text_job(job_id=jid, texts=texts, db_session_factory=async_session))
    else:
        raise HTTPException(400, "No valid URLs or texts in file")
    return JobResp(job_id=jid, status="QUEUED", redirect_url=f"/job/{jid}")


# ── API: Results ─────────────────────────────────────────────────────

@app.get("/api/v1/results/{jid}")
async def get_results(jid: str):
    async with async_session() as s:
        job = await s.get(Job, jid)
        if not job:
            raise HTTPException(404)
        results = (await s.execute(
            select(ResultORM).where(ResultORM.job_id == jid).order_by(ResultORM.analyzed_at.desc())
        )).scalars().all()
    return {
        "job_id": jid, "status": job.status,
        "results": [{
            "url": r.source_url, "title": r.title, "snippet": r.content_snippet,
            "sentiment": r.sentiment, "confidence": r.confidence,
            "language": r.language, "sarcasm_detected": r.sarcasm_detected,
            "model_used": r.model_used,
        } for r in results],
    }


@app.get("/api/v1/export/{jid}.{fmt}")
async def export_results(jid: str, fmt: str):
    if fmt not in ("csv", "json"):
        raise HTTPException(400)
    async with async_session() as s:
        job = await s.get(Job, jid)
        if not job:
            raise HTTPException(404)
        results = (await s.execute(select(ResultORM).where(ResultORM.job_id == jid))).scalars().all()
    if fmt == "json":
        data = [{
            "url": r.source_url, "title": r.title, "sentiment": r.sentiment,
            "confidence": r.confidence, "language": r.language, "text": r.content_snippet,
        } for r in results]
        return StreamingResponse(
            iter([json.dumps(data, indent=2, ensure_ascii=False)]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={jid}.json"},
        )
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["URL", "Title", "Sentiment", "Confidence", "Language", "Text"])
    for r in results:
        w.writerow([r.source_url, r.title, r.sentiment, r.confidence, r.language, r.content_snippet[:300]])
    out.seek(0)
    return StreamingResponse(
        iter([out.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={jid}.csv"},
    )


# ── API: History / Management ────────────────────────────────────────

@app.get("/api/v1/jobs")
async def list_jobs(limit: int = 50, offset: int = 0):
    async with async_session() as s:
        jobs = (await s.execute(
            select(Job).order_by(Job.created_at.desc()).limit(limit).offset(offset)
        )).scalars().all()
        total = (await s.execute(select(func.count(Job.id)))).scalar() or 0
    return {
        "total": total, "limit": limit, "offset": offset,
        "jobs": [{
            "id": j.id, "status": j.status, "input_type": j.input_type,
            "source_type": j.source_type, "keyword": j.keyword,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        } for j in jobs],
    }


@app.delete("/api/v1/jobs/{jid}")
async def delete_job(jid: str):
    async with async_session() as s:
        job = await s.get(Job, jid)
        if not job:
            raise HTTPException(404)
        await s.execute(delete(ResultORM).where(ResultORM.job_id == jid))
        await s.delete(job)
        await s.commit()
    return {"deleted": jid}


@app.get("/api/v1/news/feeds")
async def list_news_feeds():
    from src.crawler.news import NEWS_FEEDS
    return {"feeds": NEWS_FEEDS}


# ── SSE + Health ─────────────────────────────────────────────────────

@app.get("/api/v1/stream/{jid}")
async def stream_progress(jid: str):
    q = await tracker.subscribe(jid)

    async def gen():
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"data: {ev.to_json()}\n\n"
                    if ev.event_type in ("COMPLETED", "ERROR"):
                        yield "event: done\ndata: {}\n\n"
                        break
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await tracker.unsubscribe(jid, q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no",
    })


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "version": "3.0.0", "llm_enabled": settings.has_llm}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,
        log_level=settings.log_level.lower(),
    )