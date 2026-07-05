"""
Telegram bot integration
Handles bot commands and message sending
Follows specifications from 02-Architecture-and-Cloud-Ecosystem.md
"""

import os
from typing import Optional
from telegram import Bot, Update
from telegram.ext import Application
from dotenv import load_dotenv

load_dotenv()


class TelegramBot:
    """Telegram bot client for sending messages and handling updates"""
    
    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN must be set in environment variables")
        
        self.bot = Bot(token=self.bot_token)
        self.admin_chat_id = os.getenv("ADMIN_CHAT_ID")
    
    async def send_message(self, chat_id: str, text: str) -> bool:
        """Send a text message to a chat"""
        try:
            await self.bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown')
            return True
        except Exception as e:
            try:
                await self.bot.send_message(chat_id=chat_id, text=f"Failed with Markdown. Error: {str(e)}")
                return True
            except Exception as inner_e:
                print(f"Failed to send message completely: {str(inner_e)}")
                try:
                    from app.core.database import get_db
                    get_db().buffer_failed_digest(f"SEND_MESSAGE_FATAL: {str(inner_e)}", "error")
                except:
                    pass
                return False
    
    async def send_admin_alert(self, message: str) -> bool:
        """
        Send an alert to the admin (Fail-Loud pattern)
        Used when API failures occur
        """
        if not self.admin_chat_id:
            print("ADMIN_CHAT_ID not configured, cannot send alert")
            return False
        
        alert_text = f"🚨 *JIT News Alert*\n\n{message}"
        return await self.send_message(self.admin_chat_id, alert_text)
    
    async def send_digest_link(self, chat_id: str, telegraph_url: str) -> bool:
        """Send a Telegraph digest link to a chat"""
        message = f"📰 *Morning Digest Ready*\n\n[Read here]({telegraph_url})"
        return await self.send_message(chat_id, message)
    
    async def send_live_report(self, chat_id: str, report: dict) -> bool:
        """Send a live report result to a chat"""
        title = report.get('title', 'No title')
        summary = report.get('summary', 'No summary')
        source_link = report.get('source_link', '')
        
        message = f"⚡ *Live Report*\n\n*{title}*\n\n{summary}"
        
        if source_link:
            message += f"\n\n[Source]({source_link})"
        
        return await self.send_message(chat_id, message)
    
    def get_chat_id_from_update(self, update: dict) -> Optional[str]:
        """Extract chat_id from a Telegram update"""
        try:
            if 'message' in update:
                return str(update['message']['chat']['id'])
            elif 'callback_query' in update:
                return str(update['callback_query']['message']['chat']['id'])
        except (KeyError, TypeError):
            pass
        return None


# Singleton instance
_telegram_bot_instance: Optional[TelegramBot] = None


def get_telegram_bot() -> TelegramBot:
    """Get singleton Telegram bot instance"""
    global _telegram_bot_instance
    if _telegram_bot_instance is None:
        _telegram_bot_instance = TelegramBot()
    return _telegram_bot_instance
