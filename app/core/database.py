"""
Database Module for JIT News Vault
Uses service_role key for all operations (backend-only)
Follows specifications from 03-Database-Schema.md

Fixes applied:
- BUG 6: Fixed column name in delete_old_digest_buffers (created_at → generated_at)
- BUG 8: Uses config.settings instead of raw os.getenv()
"""

import datetime
import logging
from typing import List, Optional
from supabase import create_client, Client

from app.core.config import settings

logger = logging.getLogger("jit_news_bot")


class Database:
    """Database client using service_role key (backend-only access)"""

    def __init__(self):
        if not settings.supabase_url or not settings.supabase_service_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment variables")

        self.client: Client = create_client(settings.supabase_url, settings.supabase_service_key)

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
        current_settings = self.get_bot_settings()
        current_tags = current_settings.get("tags", [])

        if tag not in current_tags:
            current_tags.append(tag)
            response = self.client.table("bot_settings").update({"tags": current_tags}).eq("id", 1).execute()
            return response.data[0] if response.data else current_settings
        return current_settings

    def remove_tag(self, tag: str) -> dict:
        """Remove a tag from the tags array in bot_settings"""
        current_settings = self.get_bot_settings()
        current_tags = current_settings.get("tags", [])

        if tag in current_tags:
            current_tags.remove(tag)
            response = self.client.table("bot_settings").update({"tags": current_tags}).eq("id", 1).execute()
            return response.data[0] if response.data else current_settings
        return current_settings

    def add_source(self, source: str) -> dict:
        """Add a source URL to the sources array in bot_settings"""
        current_settings = self.get_bot_settings()
        current_sources = current_settings.get("sources", [])

        if source not in current_sources:
            current_sources.append(source)
            response = self.client.table("bot_settings").update({"sources": current_sources}).eq("id", 1).execute()
            return response.data[0] if response.data else current_settings
        return current_settings

    def remove_source(self, source: str) -> dict:
        """Remove a source URL from the sources array in bot_settings"""
        current_settings = self.get_bot_settings()
        current_sources = current_settings.get("sources", [])

        if source in current_sources:
            current_sources.remove(source)
            response = self.client.table("bot_settings").update({"sources": current_sources}).eq("id", 1).execute()
            return response.data[0] if response.data else current_settings
        return current_settings

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

    def get_delivered_urls_bulk(self, url_list: List[str]) -> set:
        """Bulk check which URLs have already been delivered (Solves N+1 query problem)"""
        if not url_list:
            return set()
        response = self.client.table("url_history").select("url").in_("url", url_list).execute()
        return {item["url"] for item in response.data}

    def delete_old_digest_buffers(self, days_old: int = 7) -> None:
        """
        Delete old digest buffers to prevent table bloat.
        BUG 6 FIX: Uses 'generated_at' to match the actual schema.sql column name
        (was previously 'created_at' which doesn't exist in the digest_buffer table).
        """
        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_old)).isoformat()
        try:
            self.client.table("digest_buffer").delete().lt("generated_at", cutoff).execute()
            logger.info(f"Log rotation: deleted digest_buffer entries older than {days_old} days")
        except Exception as e:
            logger.error(f"Log rotation failed: {e}")

    def has_digest_been_sent_today(self) -> bool:
        """
        Check if today's digest has already been delivered (IST date).
        Uses digest_buffer with status='digest_delivered' and today's IST date.
        This prevents duplicate deliveries when the cron fires multiple times
        within the wider ±30 minute time window.
        """
        try:
            import pytz
            ist = pytz.timezone("Asia/Kolkata")
            today_ist = datetime.datetime.now(ist).strftime("%Y-%m-%d")

            # Check for a delivery marker for today
            response = self.client.table("digest_buffer") \
                .select("id") \
                .eq("status", "digest_delivered") \
                .gte("generated_at", f"{today_ist}T00:00:00+05:30") \
                .lte("generated_at", f"{today_ist}T23:59:59+05:30") \
                .limit(1) \
                .execute()

            return len(response.data) > 0
        except Exception as e:
            logger.error(f"Failed to check today's digest status: {e}")
            return False  # Fail-open: allow delivery if check fails

    def mark_digest_sent_today(self) -> None:
        """
        Record that today's digest was successfully delivered.
        Inserts a marker row into digest_buffer with status='digest_delivered'.
        """
        try:
            self.client.table("digest_buffer").insert({
                "content_payload": f"Digest delivered at {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
                "status": "digest_delivered"
            }).execute()
            logger.info("Marked today's digest as delivered")
        except Exception as e:
            logger.error(f"Failed to mark digest as delivered: {e}")

    def clean_stale_homepage_urls(self, source_urls: List[str]) -> int:
        """
        Remove stale homepage URLs from url_history.
        These were incorrectly stored by the old scraper that deduped on
        source homepage URLs instead of individual article URLs.
        Returns the count of removed entries.
        """
        removed = 0
        for url in source_urls:
            try:
                response = self.client.table("url_history").delete().eq("url", url).execute()
                if response.data:
                    removed += len(response.data)
                    logger.info(f"Cleaned stale homepage URL: {url}")
            except Exception as e:
                logger.warning(f"Failed to clean URL {url}: {e}")
        return removed


# Singleton instance
_db_instance: Optional[Database] = None


def get_db() -> Database:
    """Get singleton database instance"""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
