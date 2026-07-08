"""
Configuration module for environment variables
Follows specifications from 06-Environment-Variables.md
"""

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Supabase Configuration
    supabase_url: str
    supabase_service_key: str
    
    # Firecrawl API
    firecrawl_api_key: str
    
    # Groq API
    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"
    
    # Telegram Bot Configuration
    telegram_bot_token: str
    telegram_secret_token: str
    admin_chat_id: str
    
    # Cron-job.org Authentication
    cron_secret_token: str
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
