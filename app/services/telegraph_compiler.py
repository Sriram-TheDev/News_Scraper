"""
Telegraph compiler module
Converts structured JSON to Telegraph pages with SSRF protection
Follows specifications from 04-Security-Guardrails.md

Fixes applied:
- BUG 9: SSRF allow-list aligned to spec (image/jpeg, image/png only — removed image/gif)
- ROOT-FIX-2: HTML sanitization to prevent NotAllowedTag crashes
"""

import asyncio
import logging
import re
import httpx
from typing import Dict, List, Optional
from telegraph import Telegraph

logger = logging.getLogger("jit_news_bot")

# Telegraph API allowed tags (strict whitelist)
TELEGRAPH_ALLOWED_TAGS = {
    'a', 'aside', 'b', 'blockquote', 'br', 'code', 'em', 'figcaption',
    'figure', 'h3', 'h4', 'hr', 'i', 'img', 'li', 'ol', 'p', 'pre',
    's', 'strong', 'u', 'ul'
}

# Mapping of disallowed tags to their nearest allowed equivalent
TAG_REPLACEMENTS = {
    'h1': 'h3',
    'h2': 'h3',
    'h5': 'h4',
    'h6': 'h4',
    'div': 'p',
    'span': '',       # strip span, keep content
    'section': 'p',
    'article': 'p',
    'header': 'p',
    'footer': 'p',
    'nav': '',        # strip nav entirely
    'table': 'p',
    'thead': '',
    'tbody': '',
    'tr': 'p',
    'td': '',
    'th': 'strong',
}


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

    @staticmethod
    def _sanitize_html(html_content: str) -> str:
        """
        Sanitize HTML to only contain Telegraph-allowed tags.
        
        Replaces known disallowed tags with their nearest equivalent,
        and strips any remaining unknown tags while preserving their text content.
        This prevents the telegraph.exceptions.NotAllowedTag crash that killed
        the July 9 digest (error: 'h2' tag is not allowed).
        """
        result = html_content

        # Step 1: Replace known disallowed tags with equivalents
        for bad_tag, replacement_tag in TAG_REPLACEMENTS.items():
            if replacement_tag:
                # Replace opening and closing tags
                result = re.sub(
                    rf'<{bad_tag}(\s[^>]*)?>',
                    f'<{replacement_tag}>',
                    result,
                    flags=re.IGNORECASE
                )
                result = re.sub(
                    rf'</{bad_tag}>',
                    f'</{replacement_tag}>',
                    result,
                    flags=re.IGNORECASE
                )
            else:
                # Strip tag entirely but keep content
                result = re.sub(
                    rf'</?{bad_tag}(\s[^>]*)?>',
                    '',
                    result,
                    flags=re.IGNORECASE
                )

        # Step 2: Strip any remaining unknown tags (safety net)
        def replace_unknown_tag(match):
            tag_name = match.group(1).lower().split()[0]  # Get tag name without attributes
            if tag_name.lstrip('/') in TELEGRAPH_ALLOWED_TAGS:
                return match.group(0)  # Keep allowed tags
            return ''  # Strip unknown tags

        result = re.sub(r'<(/?\w[^>]*)>', replace_unknown_tag, result)

        return result

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
        html_content = "<h3>Morning News Digest</h3>"
        for i, item in enumerate(news_items):
            title = item.get('title', 'Untitled')
            summary = item.get('summary', '')
            image_url = verified_urls[i]
            source_link = item.get('source_link', '')

            html_content += f"<hr/><h4>{title}</h4>"
            html_content += f"<p>{summary}</p>"

            if image_url:
                html_content += f'<img src="{image_url}" alt="{title}"/>'

            if source_link:
                html_content += f'<p><a href="{source_link}">Read more</a></p>'

        # Step 3: Sanitize HTML to prevent NotAllowedTag crashes
        html_content = self._sanitize_html(html_content)

        # Step 4: Run the synchronous Telegraph API in a thread to prevent blocking
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
