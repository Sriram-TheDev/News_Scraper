import os
import sys
import httpx
from dotenv import load_dotenv

def set_webhook(render_url: str):
    load_dotenv()
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    secret_token = os.getenv("TELEGRAM_SECRET_TOKEN")
    
    if not bot_token:
        print("Error: TELEGRAM_BOT_TOKEN not found in .env")
        return
        
    if not secret_token:
        print("Error: TELEGRAM_SECRET_TOKEN not found in .env")
        return

    # Clean the URL
    render_url = render_url.rstrip('/')
    if not render_url.startswith("https://"):
        print("Error: Make sure your Render URL starts with https://")
        return
        
    webhook_url = f"{render_url}/webhook"
    
    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    payload = {
        "url": webhook_url,
        "secret_token": secret_token,
        "allowed_updates": ["message", "callback_query"]
    }
    
    print(f"Setting webhook to: {webhook_url}...")
    
    try:
        response = httpx.post(url, json=payload)
        response.raise_for_status()
        result = response.json()
        
        if result.get("ok"):
            print("âœ… Webhook successfully updated!")
            print(f"Details: {result.get('description')}")
        else:
            print(f"âŒ Failed to set webhook.")
            print(f"Telegram API said: {result.get('description')}")
            
    except Exception as e:
        print(f"âŒ Error making request to Telegram API: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python set_webhook.py <RENDER_APP_URL>")
        print("Example: python set_webhook.py https://jit-news-vault.onrender.com")
        sys.exit(1)
        
    set_webhook(sys.argv[1])
