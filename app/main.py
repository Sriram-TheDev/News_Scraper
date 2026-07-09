"""
FastAPI main application
Implements webhook endpoints and command handlers
Follows specifications from 04-Security-Guardrails.md and 02-Architecture-and-Cloud-Ecosystem.md

Fixes applied:
- BUG 4: Centralized security via FastAPI Depends() for webhook/cron routes
- BUG 5: Empty scrapes are now filtered at source (scraper.py), plus secondary guard here
- BUG 10: /settime input validation (HH:MM format enforcement)
- BUG 8: Uses config.settings consistently
"""

import asyncio
import traceback
import logging
import re
from fastapi import FastAPI, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("jit_news_bot")

from app.core.database import get_db
from app.services.scraper import get_scraper
from app.services.llm import get_llm
from app.services.telegraph_compiler import get_telegraph
from app.bot.telegram_bot import get_telegram_bot
from app.core.security import (
    verify_telegram_token,
    verify_cron_token,
    verify_admin_chat_id,
    validate_time_format,
)
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown"""
    logger.info("JIT News Bot starting up...")
    yield
    logger.info("JIT News Bot shutting down...")

app = FastAPI(lifespan=lifespan)


# ==============================================================================
# Global exception handler for Fail-Loud pattern (04-Security-Guardrails.md)
# ==============================================================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Fail-Loud resilience pattern
    On any exception, log to database and alert admin via Telegram
    """
    error_message = f"Error in {request.url.path}: {str(exc)}\n\n{traceback.format_exc()}"
    logger.error(f"Global Exception Caught: {error_message}")

    # Log to digest_buffer
    try:
        db = get_db()
        await asyncio.to_thread(db.buffer_failed_digest, error_message, "error")
    except Exception as db_error:
        logger.error(f"Failed to buffer error to database: {str(db_error)}")

    # Alert admin via Telegram
    try:
        telegram_bot = get_telegram_bot()
        # Truncate error for Telegram's 4096 char limit
        short_error = error_message[:1500]
        await telegram_bot.send_admin_alert(f"🚨 *Critical Error*\n\n`{short_error}`")
    except Exception as telegram_error:
        logger.error(f"Failed to send admin alert: {str(telegram_error)}")

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"detail": "Error handled gracefully to prevent webhook loops"}
    )


# ==============================================================================
# Webhook endpoint for Telegram updates
# Auth: X-Telegram-Bot-Api-Secret-Token verified via Depends()
# ==============================================================================
@app.post("/webhook")
async def telegram_webhook(
    request: Request,
    _auth: bool = Depends(verify_telegram_token),
):
    """
    Handle incoming Telegram webhook updates
    Verified via constant-time token comparison (centralized via Depends)
    """
    # Parse update
    update = await request.json()

    # Extract chat_id
    telegram_bot = get_telegram_bot()
    chat_id = telegram_bot.get_chat_id_from_update(update)

    if not chat_id:
        return {"status": "ignored"}

    # Verify admin authorization for commands
    try:
        verify_admin_chat_id(chat_id)
    except HTTPException:
        await telegram_bot.send_message(chat_id, "⛔ Unauthorized: Only admin can use this bot")
        return {"status": "unauthorized"}

    # Handle commands
    if 'message' in update and 'text' in update['message']:
        text = update['message']['text']

        if text.startswith('/'):
            await handle_command(chat_id, text)

    return {"status": "ok"}


# ==============================================================================
# Cron endpoint for scheduled digest
# Auth: X-Cron-Secret-Token verified via Depends()
# ==============================================================================
@app.post("/cron-digest")
async def cron_digest(
    _auth: bool = Depends(verify_cron_token),
):
    """
    Handle cron-job.org heartbeat for scheduled digest
    Verified via constant-time token comparison (centralized via Depends)
    """
    try:
        import datetime
        import pytz

        # Get bot settings
        db = get_db()
        bot_settings = await asyncio.to_thread(db.get_bot_settings)

        # 1. Enforce Delivery Time (IST +05:30)
        delivery_time = bot_settings.get('delivery_time')
        if delivery_time:
            try:
                ist = pytz.timezone('Asia/Kolkata')
                now_ist = datetime.datetime.now(ist)

                target_hour, target_minute = map(int, delivery_time.split(':'))
                
                # Check if current time is within +/- 15 minutes, properly handling midnight wraparounds
                now_mins = now_ist.hour * 60 + now_ist.minute
                target_mins = target_hour * 60 + target_minute
                
                diff_minutes = min(
                    abs(now_mins - target_mins),
                    1440 - abs(now_mins - target_mins)
                )

                if diff_minutes > 15:
                    return {
                        "status": "skipped",
                        "detail": f"Time mismatch. Current IST: {now_ist.strftime('%H:%M')}, Target: {delivery_time}"
                    }
            except Exception as e:
                logger.error(f"Timezone parsing failed for '{delivery_time}': {e}")

        sources = bot_settings.get('sources', [])
        tags = bot_settings.get('tags', [])

        if not sources:
            await get_telegram_bot().send_admin_alert("No sources configured for digest")
            return {"status": "no_sources"}

        # Scrape all sources (empty/failed scrapes are already filtered by scraper)
        scraper = get_scraper()
        scraped_data = await asyncio.to_thread(scraper.scrape_multiple_urls, sources)

        if not scraped_data:
            await get_telegram_bot().send_admin_alert("All sources failed to scrape — no data available")
            return {"status": "scrape_failed"}

        # Bulk query for deduplication (Fixes N+1 issue)
        detected_urls = [item['url'] for item in scraped_data]
        delivered_urls = await asyncio.to_thread(db.get_delivered_urls_bulk, detected_urls)

        news_items = []
        for item in scraped_data:
            url = item['url']
            if url not in delivered_urls:
                # Secondary guard: skip items with empty markdown (shouldn't happen after scraper fix)
                if not item.get('markdown', '').strip():
                    logger.warning(f"Skipping {url}: empty markdown content")
                    continue

                # Synthesize with LLM
                llm = get_llm()
                try:
                    synthesized = await llm.synthesize_digest_async(item['markdown'], tags)
                    synthesized['source_link'] = url
                    news_items.append(synthesized)
                except Exception as e:
                    logger.warning(f"Skipping article from {url} due to synthesis error: {e}")
                    continue

        if not news_items:
            # Avoid sending admin alerts for "No new news" to prevent spam during duplicate
            # cron ping windows (if scheduled cron hits >1 times in the 15m threshold).
            logger.info("No new news to deliver.")
            return {"status": "no_new_news"}

        # Compile to Telegraph page concurrently
        telegraph = get_telegraph()
        telegraph_url = await telegraph.compile_digest_page_async(news_items)

        # Send to admin
        telegram_bot = get_telegram_bot()
        await telegram_bot.send_digest_link(settings.admin_chat_id, telegraph_url)

        # Mark all URLs as delivered ONLY after successful Telegram delivery
        for item in news_items:
            await asyncio.to_thread(db.mark_url_delivered, item['source_link'])

        # Perform routine database cleanup (Log rotation)
        await asyncio.to_thread(db.delete_old_digest_buffers, 7)

        return {"status": "success", "telegraph_url": telegraph_url}

    except Exception as e:
        # Global exception handler will catch this and alert admin
        raise e


# ==============================================================================
# Search endpoint for live reporter (standalone API — not via Telegram webhook)
# Auth: X-Telegram-Bot-Api-Secret-Token verified via Depends()
# ==============================================================================
@app.post("/search")
async def search_command(
    request: Request,
    _auth: bool = Depends(verify_telegram_token),
):
    """
    Handle /search command for live reporting
    Stateless - does not read/write to database (per 01-Philosophy-and-Blueprint.md)
    """
    # Parse request
    data = await request.json()
    query = data.get('query', '')
    chat_id = data.get('chat_id', '')

    if not query:
        return {"status": "error", "detail": "Query required"}

    # Verify admin
    try:
        verify_admin_chat_id(chat_id)
    except HTTPException:
        return {"status": "unauthorized"}

    try:
        # Perform search (stateless - thread isolated)
        scraper = get_scraper()
        search_results = await asyncio.to_thread(scraper.search_query, query)

        if not search_results:
            telegram_bot = get_telegram_bot()
            await telegram_bot.send_message(chat_id, "No results found")
            return {"status": "no_results"}

        # Synthesize with LLM
        llm = get_llm()
        report = await llm.synthesize_live_report_async(search_results, query)

        # Send result
        telegram_bot = get_telegram_bot()
        await telegram_bot.send_live_report(chat_id, report)

        return {"status": "success"}

    except Exception as e:
        raise e


# ==============================================================================
# Command handler
# ==============================================================================
async def handle_command(chat_id: str, text: str):
    """Handle bot commands"""
    db = get_db()
    telegram_bot = get_telegram_bot()

    if text == '/start':
        await telegram_bot.send_message(
            chat_id,
            "👋 *Welcome to JIT News Bot*\n\n"
            "Commands:\n"
            "/addtag [tag] - Add a news tag\n"
            "/removetag [tag] - Remove a tag\n"
            "/addsource [url] - Add a news source\n"
            "/removesource [url] - Remove a source\n"
            "/settime [HH:MM] - Set delivery time (24h)\n"
            "/search [query] - Live news search\n"
            "/status - Show current settings"
        )

    elif text.startswith('/addtag '):
        tag = text[8:].strip()
        if tag:
            await asyncio.to_thread(db.add_tag, tag)
            await telegram_bot.send_message(chat_id, f"✅ Added tag: {tag}")

    elif text.startswith('/removetag '):
        tag = text[11:].strip()
        if tag:
            await asyncio.to_thread(db.remove_tag, tag)
            await telegram_bot.send_message(chat_id, f"✅ Removed tag: {tag}")

    elif text.startswith('/addsource '):
        source = text[11:].strip()
        if source:
            await asyncio.to_thread(db.add_source, source)
            await telegram_bot.send_message(chat_id, f"✅ Added source: {source}")

    elif text.startswith('/removesource '):
        source = text[14:].strip()
        if source:
            await asyncio.to_thread(db.remove_source, source)
            await telegram_bot.send_message(chat_id, f"✅ Removed source: {source}")

    elif text.startswith('/settime '):
        time_value = text[9:].strip()
        if time_value:
            # BUG 10 FIX: Validate time format before storing
            if not re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', time_value):
                await telegram_bot.send_message(
                    chat_id,
                    "❌ Invalid time format. Use HH:MM (24-hour format).\n"
                    "Examples: `08:00`, `15:30`, `23:45`"
                )
                return

            await asyncio.to_thread(db.update_delivery_time, time_value)
            await telegram_bot.send_message(chat_id, f"✅ Delivery time set to: {time_value} IST")

    elif text == '/status':
        bot_settings = await asyncio.to_thread(db.get_bot_settings)
        status_text = (
            f"📊 *Current Settings*\n\n"
            f"Delivery Time: {bot_settings.get('delivery_time', 'N/A')} IST\n"
            f"Tags: {', '.join(bot_settings.get('tags', []))}\n"
            f"Sources: {len(bot_settings.get('sources', []))} configured"
        )
        await telegram_bot.send_message(chat_id, status_text)

    elif text.startswith('/search '):
        query = text[8:].strip()
        if query:
            await telegram_bot.send_message(chat_id, f"🔍 Searching live web for: {query}...")
            try:
                scraper = get_scraper()
                search_results = await asyncio.to_thread(scraper.search_query, query)

                if not search_results:
                    await telegram_bot.send_message(chat_id, "No results found on the web.")
                else:
                    llm = get_llm()
                    report = await llm.synthesize_live_report_async(search_results, query)
                    await telegram_bot.send_live_report(chat_id, report)
            except Exception as e:
                await telegram_bot.send_message(chat_id, "⚠️ Search failed during processing. Check logs.")
                raise e

    else:
        await telegram_bot.send_message(chat_id, "❓ Unknown command. Use /start for help.")


# ==============================================================================
# Health check endpoint — no auth required (intentional)
# ==============================================================================
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
