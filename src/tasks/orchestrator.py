"""Task orchestrator — runs crawl → NLP pipelines for every input type."""
from __future__ import annotations
import asyncio, logging
from datetime import datetime, timezone
from src.crawler.engine import AsyncCrawler
from src.nlp.pipeline import get_pipeline, SentimentResult as NLPResult
from src.tasks.progress import tracker
from src.models import Job, SentimentResult as ResultORM

logger = logging.getLogger(__name__)


async def run_analysis_job(job_id, urls, max_depth=None, db_session_factory=None):
    """Standard URL crawl → analyse pipeline."""
    pipeline = get_pipeline()

    await tracker.update(job_id, status="CRAWLING", event_type="STATUS")
    
    async def _on_res(res):
        await tracker.update(job_id, current_url=res.url, event_type="CRAWL_RESULT")
    async def _on_prog(count):
        await tracker.update(job_id, crawled=count, event_type="PROGRESS")
        
    crawler = AsyncCrawler(max_depth=max_depth, on_result=_on_res, on_progress=_on_prog)
    try:
        crawl_results = await crawler.crawl(urls)
    except Exception as e:
        logger.error("Crawl gagal %s: %s", job_id, e)
        await tracker.update(job_id, status="ERROR", error_message=str(e), event_type="ERROR")
        await _upd(job_id, "FAILED", db_session_factory, str(e))
        return

    if not crawl_results:
        await tracker.update(job_id, status="ERROR", error_message="No content found", event_type="ERROR")
        await _upd(job_id, "FAILED", db_session_factory, "No content found")
        return

    await _run_nlp(job_id, [(cr.url, cr.title, cr.text) for cr in crawl_results], pipeline, db_session_factory)


async def run_keyword_job(job_id, keyword, max_results=10, engine="duckduckgo", site_filter=None, max_depth=1, db_session_factory=None):
    """Keyword search → crawl → analyse pipeline."""
    from src.crawler.search import keyword_to_urls
    pipeline = get_pipeline()
    await tracker.update(job_id, status="SEARCHING", event_type="STATUS")

    try:
        urls = await keyword_to_urls(keyword, max_results=max_results, engine=engine, site_filter=site_filter)
    except Exception as e:
        logger.error("Search gagal %s: %s", job_id, e)
        await tracker.update(job_id, status="ERROR", error_message=str(e), event_type="ERROR")
        await _upd(job_id, "FAILED", db_session_factory, str(e))
        return

    if not urls:
        await tracker.update(job_id, status="ERROR", error_message="No search results", event_type="ERROR")
        await _upd(job_id, "FAILED", db_session_factory, "No search results")
        return

    await tracker.update(job_id, status="CRAWLING", total=len(urls), event_type="STATUS")

    async def _on_res(res):
        await tracker.update(job_id, current_url=res.url, event_type="CRAWL_RESULT")
    async def _on_prog(count):
        await tracker.update(job_id, crawled=count, event_type="PROGRESS")
        
    crawler = AsyncCrawler(max_depth=max_depth, on_result=_on_res, on_progress=_on_prog)
    try:
        crawl_results = await crawler.crawl(urls)
    except Exception as e:
        logger.error("Crawl gagal %s: %s", job_id, e)
        await tracker.update(job_id, status="ERROR", error_message=str(e), event_type="ERROR")
        await _upd(job_id, "FAILED", db_session_factory, str(e))
        return

    if not crawl_results:
        await tracker.update(job_id, status="ERROR", error_message="No content crawled", event_type="ERROR")
        await _upd(job_id, "FAILED", db_session_factory, "No content crawled")
        return

    await _run_nlp(job_id, [(cr.url, cr.title, cr.text) for cr in crawl_results], pipeline, db_session_factory)


async def run_text_job(job_id, texts, db_session_factory=None):
    """Direct text analysis — skip crawling entirely."""
    pipeline = get_pipeline()
    await tracker.update(job_id, status="NLP_PROCESSING", total=len(texts), event_type="STATUS")
    await _run_nlp(job_id, [("direct-input", f"Text #{i+1}", t) for i, t in enumerate(texts)], pipeline, db_session_factory)


async def run_social_job(job_id, platforms, query, max_results=50, db_session_factory=None, **kwargs):
    """Social media scrape → analyse pipeline."""
    from src.crawler.social import scrape_social, TwitterScraper, RedditScraper
    pipeline = get_pipeline()
    include_comments = kwargs.get("include_comments", False)
    
    await tracker.update(job_id, status="SCRAPING", event_type="STATUS")

    all_posts = []
    errors = []
    for platform in platforms:
        try:
            posts = await scrape_social(platform, query, max_results, **kwargs)
            all_posts.extend(posts)
        except Exception as e:
            logger.error("Social scrape gagal untuk %s pada job %s: %s", platform, job_id, e)
            errors.append(f"{platform}: {e}")

    if not all_posts:
        err_msg = "; ".join(errors) if errors else "No social posts found on any platform"
        await tracker.update(job_id, status="ERROR", error_message=err_msg, event_type="ERROR")
        await _upd(job_id, "FAILED", db_session_factory, err_msg)
        return

    all_items = []
    for p in all_posts:
        all_items.append((p.url, f"{p.platform}/@{p.author}", p.text))
        
    if include_comments:
        await tracker.update(job_id, status="SCRAPING_COMMENTS", event_type="STATUS")
        comment_tasks = []
        for p in all_posts:
            if p.platform == "twitter":
                scr = TwitterScraper()
                if "/status/" in p.url:
                    comment_tasks.append(scr.get_comments(p.url, max_comments=10))
            elif p.platform == "reddit":
                scr = RedditScraper()
                comment_tasks.append(scr.get_comments(p.url, max_comments=10))
            
        if comment_tasks:
            results = await asyncio.gather(*comment_tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, list):
                    for c in res:
                        all_items.append((c.url, f"{c.platform}/@{c.author} (reply)", c.text))

    await tracker.update(job_id, status="NLP_PROCESSING", total=len(all_items), event_type="STATUS")
    await _run_nlp(job_id, all_items, pipeline, db_session_factory)


async def run_news_job(job_id, keyword=None, sources=None, feed_url=None, max_articles=20, db_session_factory=None):
    """News RSS → full article → analyse pipeline."""
    from src.crawler.news import NewsScraper
    pipeline = get_pipeline()
    await tracker.update(job_id, status="SCRAPING", event_type="STATUS")

    ns = NewsScraper()
    try:
        if keyword:
            articles = await ns.search_news(keyword, sources=sources, max_per_source=max(max_articles // max(len(sources or [1]), 1), 3))
        elif feed_url:
            articles = await ns.scrape_rss_full(feed_url=feed_url, max_articles=max_articles)
        elif sources:
            articles = []
            for src in sources:
                articles.extend(await ns.scrape_rss_full(feed_name=src, max_articles=max_articles // len(sources)))
        else:
            articles = await ns.scrape_rss(feed_name="kompas", max_articles=max_articles)
    except Exception as e:
        logger.error("News scrape gagal %s: %s", job_id, e)
        await tracker.update(job_id, status="ERROR", error_message=str(e), event_type="ERROR")
        await _upd(job_id, "FAILED", db_session_factory, str(e))
        return

    if not articles:
        await tracker.update(job_id, status="ERROR", error_message="No news articles found", event_type="ERROR")
        await _upd(job_id, "FAILED", db_session_factory, "No news articles found")
        return

    await tracker.update(job_id, status="NLP_PROCESSING", total=len(articles), event_type="STATUS")
    items = [(a.url, a.title, a.text) for a in articles if a.text]
    await _run_nlp(job_id, items, pipeline, db_session_factory)


# ── shared NLP + save ────────────────────────────────────────────────

async def _run_nlp(job_id, items, pipeline, db_session_factory):
    """Run NLP analysis on a list of (url, title, text) tuples."""
    counts = {"positive": 0, "negative": 0, "neutral": 0, "mixed": 0}
    all_results = []
    for i, (url, title, text) in enumerate(items):
        if not text or len(text) < 10:
            continue
        nr = pipeline.analyze(text)
        all_results.append((url, title, text, nr))
        counts[nr.sentiment.value] = counts.get(nr.sentiment.value, 0) + 1
        await tracker.update(
            job_id, 
            analyzed=i + 1, 
            progress=int((i + 1) / len(items) * 100), 
            current_url=url, 
            last_title=title,
            last_sentiment=nr.sentiment.value,
            last_confidence=nr.confidence,
            event_type="NLP_RESULT"
        )


    if db_session_factory:
        await _save(job_id, all_results, db_session_factory)

    t = sum(counts.values())
    summary = {
        "total_analyzed": t,
        "positive": counts.get("positive", 0),
        "negative": counts.get("negative", 0),
        "neutral": counts.get("neutral", 0),
        "mixed": counts.get("mixed", 0),
        "positive_pct": round(counts.get("positive", 0) / t * 100, 1) if t else 0,
        "negative_pct": round(counts.get("negative", 0) / t * 100, 1) if t else 0,
        "neutral_pct": round(counts.get("neutral", 0) / t * 100, 1) if t else 0,
    }
    await tracker.update(job_id, status="COMPLETED", progress=100, event_type="COMPLETED", **summary)
    await _upd(job_id, "COMPLETED", db_session_factory)
    logger.info("Job %s selesai: %s", job_id, summary)


async def _upd(jid, status, factory, err=None):
    if not factory:
        return
    async with factory() as s:
        j = await s.get(Job, jid)
        if j:
            j.status = status
            j.error_message = err
            if status == "COMPLETED":
                j.completed_at = datetime.now(timezone.utc)
        await s.commit()


async def _save(jid, results, factory):
    async with factory() as s:
        for url, title, text, nr in results:
            s.add(ResultORM(
                job_id=jid, source_url=url, title=title,
                content_snippet=nr.text[:500], full_content=nr.text,
                sentiment=nr.sentiment.value, confidence=nr.confidence,
                model_used=nr.model_used, language=nr.language,
                sarcasm_detected=nr.sarcasm_detected,
                sarcasm_confidence=nr.sarcasm_confidence,
                aspects=nr.aspects, raw_scores=nr.raw_scores,
            ))
        await s.commit()