"""FastAPI entry point."""
import asyncio,csv,io,json,logging
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from uuid import uuid4
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import HTMLResponse,StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select,func
from src.config import settings
from src.database import init_db,async_session
from src.models import Job,SentimentResult as ResultORM
from src.tasks.progress import tracker
from src.tasks.orchestrator import run_analysis_job
logging.basicConfig(level=getattr(logging,settings.log_level),format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",datefmt="%H:%M:%S")
logger=logging.getLogger(__name__)
@asynccontextmanager
async def lifespan(app):
    settings.data_dir.mkdir(parents=True,exist_ok=True);(settings.data_dir/"exports").mkdir(exist_ok=True);(settings.data_dir/"logs").mkdir(exist_ok=True)
    await init_db();logger.info(f"Siap di http://{settings.app_host}:{settings.app_port}");yield;logger.info("Shutdown")
app=FastAPI(title="SentimentTools",version="2.0.0",lifespan=lifespan)
app.mount("/static",StaticFiles(directory="static"),name="static")
templates=Jinja2Templates(directory="src/templates")
class AnalysisReq(BaseModel):
    urls:list[str];depth:int=2;use_js_rendering:bool=False
class JobResp(BaseModel):
    job_id:str;status:str;redirect_url:str
@app.get("/",response_class=HTMLResponse)
async def index(request:Request):return templates.TemplateResponse("index.html",{"request":request})
@app.get("/job/{jid}",response_class=HTMLResponse)
async def job_page(request:Request,jid:str):
    st=tracker.get_state(jid)
    if not st:raise HTTPException(404)
    return templates.TemplateResponse("job.html",{"request":request,"job_id":jid,"initial_state":st})
@app.get("/results/{jid}",response_class=HTMLResponse)
async def results_page(request:Request,jid:str):
    async with async_session() as s:
        job=await s.get(Job,jid)
        if not job:raise HTTPException(404)
        stmt=select(ResultORM.sentiment,func.count(ResultORM.id),func.avg(ResultORM.confidence)).where(ResultORM.job_id==jid).group_by(ResultORM.sentiment)
        rows=(await s.execute(stmt)).all();summary={r[0]:{"count":r[1],"avg_confidence":round(r[2],3) if r[2] else 0} for r in rows}
        total=(await s.execute(select(func.count(ResultORM.id)).where(ResultORM.job_id==jid))).scalar() or 0
        results=(await s.execute(select(ResultORM).where(ResultORM.job_id==jid).order_by(ResultORM.analyzed_at.desc()))).scalars().all()
    return templates.TemplateResponse("results.html",{"request":request,"job_id":jid,"job":job,"summary":summary,"total":total,"results":results})
@app.post("/api/v1/analysis",response_model=JobResp)
async def create_analysis(req:AnalysisReq):
    if not req.urls:raise HTTPException(400,"Min 1 URL")
    valid=[u.strip() for u in req.urls if u.strip().startswith("http")]
    if not valid:raise HTTPException(400,"No valid URL")
    jid=str(uuid4())
    async with async_session() as s:
        s.add(Job(id=jid,status="QUEUED",input_type="url",input_data={"urls":valid},config={"depth":req.depth},started_at=datetime.now(timezone.utc)));await s.commit()
    asyncio.create_task(run_analysis_job(job_id=jid,urls=valid,max_depth=req.depth if req.depth!=2 else None,db_session_factory=async_session))
    return JobResp(job_id=jid,status="QUEUED",redirect_url=f"/job/{jid}")
@app.get("/api/v1/results/{jid}")
async def get_results(jid:str):
    async with async_session() as s:
        job=await s.get(Job,jid)
        if not job:raise HTTPException(404)
        results=(await s.execute(select(ResultORM).where(ResultORM.job_id==jid).order_by(ResultORM.analyzed_at.desc()))).scalars().all()
    return {"job_id":jid,"status":job.status,"results":[{"url":r.source_url,"title":r.title,"snippet":r.content_snippet,"sentiment":r.sentiment,"confidence":r.confidence,"language":r.language,"sarcasm_detected":r.sarcasm_detected,"model_used":r.model_used} for r in results]}
@app.get("/api/v1/export/{jid}.{fmt}")
async def export_results(jid:str,fmt:str):
    if fmt not in("csv","json"):raise HTTPException(400)
    async with async_session() as s:
        job=await s.get(Job,jid)
        if not job:raise HTTPException(404)
        results=(await s.execute(select(ResultORM).where(ResultORM.job_id==jid))).scalars().all()
    if fmt=="json":
        data=[{"url":r.source_url,"title":r.title,"sentiment":r.sentiment,"confidence":r.confidence,"language":r.language,"text":r.content_snippet} for r in results]
        return StreamingResponse(iter([json.dumps(data,indent=2,ensure_ascii=False)]),media_type="application/json",headers={"Content-Disposition":f"attachment; filename={jid}.json"})
    out=io.StringIO();w=csv.writer(out);w.writerow(["URL","Title","Sentiment","Confidence","Language","Text"])
    for r in results:w.writerow([r.source_url,r.title,r.sentiment,r.confidence,r.language,r.content_snippet[:300]])
    out.seek(0);return StreamingResponse(iter([out.getvalue()]),media_type="text/csv",headers={"Content-Disposition":f"attachment; filename={jid}.csv"})
@app.get("/api/v1/stream/{jid}")
async def stream_progress(jid:str):
    q=await tracker.subscribe(jid)
    async def gen():
        try:
            while True:
                try:
                    ev=await asyncio.wait_for(q.get(),timeout=30.0);yield f"data: {ev.to_json()}\n\n"
                    if ev.event_type in("COMPLETED","ERROR"):yield "event: done\ndata: {}\n\n";break
                except asyncio.TimeoutError:yield ": keepalive\n\n"
        except asyncio.CancelledError:pass
        finally:await tracker.unsubscribe(jid,q)
    return StreamingResponse(gen(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","Connection":"keep-alive","X-Accel-Buffering":"no"})
@app.get("/api/v1/health")
async def health():return {"status":"ok","version":"2.0.0","llm_enabled":settings.has_llm}
if __name__=="__main__":
    import uvicorn;uvicorn.run("src.main:app",host=settings.app_host,port=settings.app_port,reload=settings.app_debug,log_level=settings.log_level.lower())