"""
FastAPI main application
Implements webhook endpoints and command handlers
Follows specifications from 04-Security-Guardrails.md and 02-Architecture-and-Cloud-Ecosystem.md
"""

import os
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import traceback
from app.core.database import get_db
from app.services.scraper import get_scraper
from app.services.llm import get_llm
from app.services.telegraph_compiler import get_telegraph
from app.bot.telegram_bot import get_telegram_bot
from app.core.security import verify_telegram_token, verify_cron_token, verify_admin_chat_id
from app.core.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown"""
    # Startup
    print("JIT News Bot starting up...")
    yield
    # Shutdown
    print("JIT News Bot shutting down...")


app = FastAPI(lifespan=lifespan)


# Global exception handler for Fail-Loud pattern
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Fail-Loud resilience pattern
    On any exception, log to database and alert admin via Telegram
    """
    error_message = f"Error in {request.url.path}: {str(exc)}\n\n{traceback.format_exc()}"
    
    # Log to digest_buffer
    try:
        db = get_db()
        db.buffer_failed_digest(error_message, status="error")
    except Exception as db_error:
        print(f"Failed to buffer error to database: {str(db_error)}")
    
    # Alert admin via Telegram
    try:
        telegram_bot = get_telegram_bot()
        await telegram_bot.send_admin_alert(f"🚨 *Critical Error*\n\n{error_message}")
    except Exception as telegram_error:
        print(f"Failed to send admin alert: {str(telegram_error)}")
    
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"detail": "Error handled gracefully to prevent webhook loops"}
    )


# Webhook endpoint for Telegram updates
@app.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None)
):
    """
    Handle incoming Telegram webhook updates
    Verified via constant-time token comparison
    """
    # Verify token
    verify_telegram_token(x_telegram_bot_api_secret_token)
    
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


# Cron endpoint for scheduled digest
@app.post("/cron-digest")
async def cron_digest(
    x_cron_secret_token: str = Header(None)
):
    """
    Handle cron-job.org heartbeat for scheduled digest
    Verified via constant-time token comparison
    """
    # Verify token
    verify_cron_token(x_cron_secret_token)
    
    try:
        # Get bot settings
        db = get_db()
        settings = db.get_bot_settings()
        
        sources = settings.get('sources', [])
        tags = settings.get('tags', [])
        
        if not sources:
            await get_telegram_bot().send_admin_alert("No sources configured for digest")
            return {"status": "no_sources"}
        
        # Scrape all sources
        scraper = get_scraper()
        scraped_data = scraper.scrape_multiple_urls(sources)
        
        # Deduplicate against url_history
        news_items = []
        for item in scraped_data:
            url = item['url']
            if not db.is_url_delivered(url):
                # Synthesize with LLM
                llm = get_llm()
                synthesized = llm.synthesize_digest(item['markdown'], tags)
                synthesized['source_link'] = url
                news_items.append(synthesized)
                
                # Mark as delivered
                db.mark_url_delivered(url)
        
        if not news_items:
            await get_telegram_bot().send_admin_alert("No new news to deliver")
            return {"status": "no_new_news"}
        
        # Compile to Telegraph page
        telegraph = get_telegraph()
        telegraph_url = telegraph.compile_digest_page(news_items)
        
        # Send to admin
        telegram_bot = get_telegram_bot()
        await telegram_bot.send_digest_link(os.getenv("ADMIN_CHAT_ID"), telegraph_url)
        
        return {"status": "success", "telegraph_url": telegraph_url}
    
    except Exception as e:
        # Global exception handler will catch this and alert admin
        raise e


# Search endpoint for live reporter
@app.post("/search")
async def search_command(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None)
):
    """
    Handle /search command for live reporting
    Stateless - does not read/write to database
    """
    # Verify token
    verify_telegram_token(x_telegram_bot_api_secret_token)
    
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
        # Perform search (stateless - no DB access)
        scraper = get_scraper()
        search_results = scraper.search_query(query)
        
        if not search_results:
            telegram_bot = get_telegram_bot()
            await telegram_bot.send_message(chat_id, "No results found")
            return {"status": "no_results"}
        
        # Synthesize with LLM
        llm = get_llm()
        report = llm.synthesize_live_report(search_results, query)
        
        # Send result
        telegram_bot = get_telegram_bot()
        await telegram_bot.send_live_report(chat_id, report)
        
        return {"status": "success"}
    
    except Exception as e:
        raise e


async def handle_command(chat_id: str, text: str):
    """Handle bot commands"""
    db = get_db()
    telegram_bot = get_telegram_bot()
    
    if text == '/start':
        await telegram_bot.send_message(
            chat_id,
            "👋 *Welcome to JIT News Bot*\n\n"
            "Commands:\n"
            "/addtag <tag> - Add a news tag\n"
            "/removetag <tag> - Remove a tag\n"
            "/addsource <url> - Add a news source\n"
            "/removesource <url> - Remove a source\n"
            "/settime <HH:MM> - Set delivery time\n"
            "/search <query> - Live news search\n"
            "/status - Show current settings"
        )
    
    elif text.startswith('/addtag '):
        tag = text[8:].strip()
        if tag:
            db.add_tag(tag)
            await telegram_bot.send_message(chat_id, f"✅ Added tag: {tag}")
    
    elif text.startswith('/removetag '):
        tag = text[11:].strip()
        if tag:
            db.remove_tag(tag)
            await telegram_bot.send_message(chat_id, f"✅ Removed tag: {tag}")
    
    elif text.startswith('/addsource '):
        source = text[11:].strip()
        if source:
            db.add_source(source)
            await telegram_bot.send_message(chat_id, f"✅ Added source: {source}")
    
    elif text.startswith('/removesource '):
        source = text[14:].strip()
        if source:
            db.remove_source(source)
            await telegram_bot.send_message(chat_id, f"✅ Removed source: {source}")
    
    elif text.startswith('/settime '):
        time = text[9:].strip()
        if time:
            db.update_delivery_time(time)
            await telegram_bot.send_message(chat_id, f"✅ Delivery time set to: {time}")
    
    elif text == '/status':
        settings = db.get_bot_settings()
        status_text = (
            f"📊 *Current Settings*\n\n"
            f"Delivery Time: {settings.get('delivery_time', 'N/A')}\n"
            f"Tags: {', '.join(settings.get('tags', []))}\n"
            f"Sources: {len(settings.get('sources', []))} configured"
        )
        await telegram_bot.send_message(chat_id, status_text)
    
    elif text.startswith('/search '):
        query = text[8:].strip()
        if query:
            await telegram_bot.send_message(chat_id, f"🔍 Searching live web for: {query}...")
            try:
                scraper = get_scraper()
                search_results = scraper.search_query(query)
                
                if not search_results:
                    await telegram_bot.send_message(chat_id, "No results found on the web.")
                else:
                    llm = get_llm()
                    report = llm.synthesize_live_report(search_results, query)
                    await telegram_bot.send_live_report(chat_id, report)
            except Exception as e:
                await telegram_bot.send_message(chat_id, f"⚠️ Search failed during processing. Check logs.")
                raise e
    
    else:
        await telegram_bot.send_message(chat_id, "❓ Unknown command. Use /start for help.")


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
