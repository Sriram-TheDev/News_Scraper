"""
Database Module for JIT News Vault
Uses service_role key for all operations (backend-only)
Follows specifications from 03-Database-Schema.md
"""

import os
from typing import List, Optional
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()


class Database:
    """Database client using service_role key (backend-only access)"""
    
    def __init__(self):
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.service_key = os.getenv("SUPABASE_SERVICE_KEY")
        
        if not self.supabase_url or not self.service_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment variables")
        
        self.client: Client = create_client(self.supabase_url, self.service_key)
    
    def get_bot_settings(self) -> dict:
        """Get the single row from bot_settings table"""
        response = self.client.table("bot_settings").select("*").limit(1).execute()
        if response.data:
            return response.data[0]
        return {}
    
    def update_delivery_time(self, time: str) -> dict:
        """Update delivery time in bot_settings"""
        response = self.client.table("bot_settings").update({"delivery_time": time}).eq("id", 1).execute()
        return response.data[0] if response.data else {}
    
    def add_tag(self, tag: str) -> dict:
        """Add a tag to the tags array in bot_settings"""
        settings = self.get_bot_settings()
        current_tags = settings.get("tags", [])
        
        if tag not in current_tags:
            current_tags.append(tag)
            response = self.client.table("bot_settings").update({"tags": current_tags}).eq("id", 1).execute()
            return response.data[0] if response.data else settings
        return settings
    
    def remove_tag(self, tag: str) -> dict:
        """Remove a tag from the tags array in bot_settings"""
        settings = self.get_bot_settings()
        current_tags = settings.get("tags", [])
        
        if tag in current_tags:
            current_tags.remove(tag)
            response = self.client.table("bot_settings").update({"tags": current_tags}).eq("id", 1).execute()
            return response.data[0] if response.data else settings
        return settings
    
    def add_source(self, source: str) -> dict:
        """Add a source URL to the sources array in bot_settings"""
        settings = self.get_bot_settings()
        current_sources = settings.get("sources", [])
        
        if source not in current_sources:
            current_sources.append(source)
            response = self.client.table("bot_settings").update({"sources": current_sources}).eq("id", 1).execute()
            return response.data[0] if response.data else settings
        return settings
    
    def remove_source(self, source: str) -> dict:
        """Remove a source URL from the sources array in bot_settings"""
        settings = self.get_bot_settings()
        current_sources = settings.get("sources", [])
        
        if source in current_sources:
            current_sources.remove(source)
            response = self.client.table("bot_settings").update({"sources": current_sources}).eq("id", 1).execute()
            return response.data[0] if response.data else settings
        return settings
    
    def is_url_delivered(self, url: str) -> bool:
        """Check if a URL has already been delivered (deduplication)"""
        response = self.client.table("url_history").select("id").eq("url", url).execute()
        return len(response.data) > 0
    
    def mark_url_delivered(self, url: str) -> dict:
        """Mark a URL as delivered in url_history"""
        response = self.client.table("url_history").insert({"url": url}).execute()
        return response.data[0] if response.data else {}
    
    def get_delivered_urls(self, limit: int = 1000) -> List[str]:
        """Get list of delivered URLs for deduplication"""
        response = self.client.table("url_history").select("url").order("sent_at", desc=True).limit(limit).execute()
        return [item["url"] for item in response.data]
    
    def buffer_failed_digest(self, content_payload: str, status: str = "failed") -> dict:
        """Buffer a failed digest to digest_buffer (Fail-Loud pattern)"""
        response = self.client.table("digest_buffer").insert({
            "content_payload": content_payload,
            "status": status
        }).execute()
        return response.data[0] if response.data else {}
    
    def get_pending_buffers(self) -> List[dict]:
        """Get all pending buffers from digest_buffer for recovery"""
        response = self.client.table("digest_buffer").select("*").eq("status", "pending").execute()
        return response.data
    
    def update_buffer_status(self, buffer_id: int, status: str) -> dict:
        """Update status of a buffer entry"""
        response = self.client.table("digest_buffer").update({"status": status}).eq("id", buffer_id).execute()
        return response.data[0] if response.data else {}


# Singleton instance
_db_instance: Optional[Database] = None


def get_db() -> Database:
    """Get singleton database instance"""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
