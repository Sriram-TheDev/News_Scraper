"""
Telegraph compiler module
Converts structured JSON to Telegraph pages with SSRF protection
Follows specifications from 04-Security-Guardrails.md

Fixes applied:
- BUG 9: SSRF allow-list aligned to spec (image/jpeg, image/png only — removed image/gif)
"""

import asyncio
import logging
import httpx
from typing import Dict, List, Optional
from telegraph import Telegraph

logger = logging.getLogger("jit_news_bot")


class TelegraphCompiler:
    """
    Compiles structured news data into Telegraph pages
    Includes SSRF protection via HEAD request verification
    """

    def __init__(self):
        self.telegraph = Telegraph()
        self.telegraph.create_account(
            short_name='JIT News Bot',
            author_name='JIT News',
            author_url='https://t.me/your_bot'
        )

    async def verify_image_url_async(self, client: httpx.AsyncClient, url: str) -> str:
        """
        Server-Side Media Verification (SSRF Protection)
        Using native async HTTPX for concurrent resolution.
        Returns the url if valid, or an empty string if invalid.

        Per 04-Security-Guardrails.md:
        - Content-Type must be strictly image/jpeg or image/png
        - Size must be under 5MB
        - Base64 and .webp URLs are rejected upstream by the LLM normalizer
        """
        if not url or not url.startswith(('http://', 'https://')):
            return ""

        try:
            response = await client.head(url, follow_redirects=True, timeout=5.0)

            if response.status_code != 200:
                return ""

            content_type = response.headers.get('content-type', '').lower()
            # Per spec 04-Security-Guardrails: strictly image/jpeg or image/png only
            # Using substring matching to handle charset suffixes (e.g. "image/jpeg; charset=utf-8")
            if not any(t in content_type for t in ['image/jpeg', 'image/png']):
                logger.debug(f"Rejected image URL with content-type '{content_type}': {url[:80]}")
                return ""

            content_length = response.headers.get('content-length')
            if content_length:
                size_mb = int(content_length) / (1024 * 1024)
                if size_mb > 5:
                    logger.debug(f"Rejected oversized image ({size_mb:.1f}MB): {url[:80]}")
                    return ""

            return url
        except Exception:
            return ""

    async def compile_digest_page_async(self, news_items: list) -> str:
        """
        Compile multiple news items into a single Telegraph digest page asynchronously.
        Verifies all image URLs concurrently for massive speedups.
        """
        # Step 1: Concurrently verify all images
        async with httpx.AsyncClient() as client:
            async def _verify_or_empty(url: str):
                if url:
                    return await self.verify_image_url_async(client, url)
                return ""

            tasks = [_verify_or_empty(item.get('image_url', '')) for item in news_items]
            verified_urls = await asyncio.gather(*tasks)

        # Step 2: Inject verified URLs back into the payload
        html_content = "<h2>Morning News Digest</h2>"
        for i, item in enumerate(news_items):
            title = item.get('title', 'Untitled')
            summary = item.get('summary', '')
            image_url = verified_urls[i]
            source_link = item.get('source_link', '')

            html_content += f"<hr/><h3>{title}</h3>"
            html_content += f"<p>{summary}</p>"

            if image_url:
                html_content += f'<img src="{image_url}" alt="{title}"/>'

            if source_link:
                html_content += f'<p><a href="{source_link}">Read more</a></p>'

        # Step 3: Run the synchronous Telegraph API in a thread to prevent blocking
        try:
            page = await asyncio.to_thread(
                self.telegraph.create_page,
                title='Morning News Digest',
                html_content=html_content,
                author_name='JIT News Bot'
            )
            return page['url']
        except Exception as e:
            raise Exception(f"Failed to create Telegraph digest page: {str(e)}")


# Singleton instance
_telegraph_instance: Optional[TelegraphCompiler] = None


def get_telegraph() -> TelegraphCompiler:
    """Get singleton Telegraph compiler instance"""
    global _telegraph_instance
    if _telegraph_instance is None:
        _telegraph_instance = TelegraphCompiler()
    return _telegraph_instance
