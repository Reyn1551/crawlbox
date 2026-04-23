"""Orchestrator."""
from __future__ import annotations
import logging
from datetime import datetime,timezone
from src.crawler.engine import AsyncCrawler
from src.nlp.pipeline import get_pipeline
from src.tasks.progress import tracker
from src.models import Job,SentimentResult as ResultORM
logger=logging.getLogger(__name__)
async def run_analysis_job(job_id,urls,max_depth=None,db_session_factory=None):
    pipeline=get_pipeline();await tracker.create_job(job_id,len(urls)*3)
    def on_cr(r):
        st=tracker.get_state(job_id);asyncio.create_task(tracker.update(job_id,status="CRAWLING",crawled=(st.get("crawled",0)+1),current_url=r.url,event_type="CRAWL_RESULT"))
    await tracker.update(job_id,status="CRAWLING",event_type="STATUS")
    crawler=AsyncCrawler(max_depth=max_depth,on_result=on_cr)
    try: crawl_results=await crawler.crawl(urls)
    except Exception as e:
        logger.error(f"Crawl gagal {job_id}:{e}");await tracker.update(job_id,status="ERROR",error_message=str(e),event_type="ERROR");await _upd(job_id,"FAILED",db_session_factory,str(e));return
    if not crawl_results: await tracker.update(job_id,status="ERROR",error_message="No content",event_type="ERROR");await _upd(job_id,"FAILED",db_session_factory,"No content");return
    await tracker.update(job_id,status="NLP_PROCESSING",total=len(crawl_results),event_type="STATUS")
    counts={"positive":0,"negative":0,"neutral":0,"mixed":0};all_r=[]
    for i,cr in enumerate(crawl_results):
        if not cr.text or len(cr.text)<20: continue
        nr=pipeline.analyze(cr.text);all_r.append((cr,nr));counts[nr.sentiment.value]=counts.get(nr.sentiment.value,0)+1
        await tracker.update(job_id,analyzed=i+1,progress=int((i+1)/len(crawl_results)*100),current_url=cr.url,event_type="NLP_RESULT")
    if db_session_factory: await _save(job_id,all_r,db_session_factory)
    t=sum(counts.values())
    summary={"total_analyzed":t,"positive":counts.get("positive",0),"negative":counts.get("negative",0),"neutral":counts.get("neutral",0),"mixed":counts.get("mixed",0),
             "positive_pct":round(counts.get("positive",0)/t*100,1) if t else 0,"negative_pct":round(counts.get("negative",0)/t*100,1) if t else 0,"neutral_pct":round(counts.get("neutral",0)/t*100,1) if t else 0}
    await tracker.update(job_id,status="COMPLETED",progress=100,event_type="COMPLETED",**summary);await _upd(job_id,"COMPLETED",db_session_factory);logger.info(f"Job {job_id} selesai:{summary}")
async def _upd(jid,status,factory,err=None):
    if not factory: return
    async with factory() as s:
        j=await s.get(Job,jid)
        if j: j.status=status;j.error_message=err
        if status=="COMPLETED": j.completed_at=datetime.now(timezone.utc)
        await s.commit()
async def _save(jid,results,factory):
    async with factory() as s:
        for cr,nr in results:
            s.add(ResultORM(job_id=jid,source_url=cr.url,title=cr.title,content_snippet=nr.text[:500],full_content=nr.text,sentiment=nr.sentiment.value,confidence=nr.confidence,model_used=nr.model_used,language=nr.language,sarcasm_detected=nr.sarcasm_detected,sarcasm_confidence=nr.sarcasm_confidence,aspects=nr.aspects,raw_scores=nr.raw_scores))
        await s.commit()