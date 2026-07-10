import asyncio
import os
import sys

# Ensure app module is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app.services.scraper import get_scraper
from app.services.llm import get_llm
from app.services.telegraph_compiler import get_telegraph
from app.bot.telegram_bot import get_telegram_bot
from app.core.config import settings

async def run_simulation():
    bot = get_telegram_bot()
    await bot.send_admin_alert("🚀 *Manual Digest Simulation Started!*\nScraping articles and parsing via LLM. Please wait approximately 60 seconds...")
    
    # 1. Scrape 
    sources = ["https://techcrunch.com", "https://example.com"]
    print("Scraping...")
    scraper = get_scraper()
    scraped_data = scraper.scrape_multiple_urls(sources)
    
    if not scraped_data:
        await bot.send_admin_alert("Scraping failed during simulation.")
        return
        
    # 2. LLM Synthesis
    print("Synthesizing...")
    llm = get_llm()
    news_items = []
    tags = ["ai", "tech"]
    for item in scraped_data:
        url = item['url']
        if not item.get('markdown', '').strip(): continue
        try:
            synthesized = await llm.synthesize_digest_async(item['markdown'], tags)
            synthesized['source_link'] = url
            news_items.append(synthesized)
            print(f"Synthesized: {url}")
        except Exception as e:
            print("Failed synthesis for", url, e)
            
    if not news_items:
        await bot.send_admin_alert("LLM failed to generate any articles.")
        return
        
    # 3. Telegraph Compile
    print("Compiling Telegraph...")
    telegraph = get_telegraph()
    try:
        telegraph_url = await telegraph.compile_digest_page_async(news_items)
    except Exception as e:
        await bot.send_admin_alert(f"Telegraph crash: {e}")
        return
    
    # 4. Telegram Send
    print("Sending via Telegram...")
    await bot.send_digest_link(settings.admin_chat_id, telegraph_url)
    print("✅ SUCCESS!")

if __name__ == "__main__":
    asyncio.run(run_simulation())
