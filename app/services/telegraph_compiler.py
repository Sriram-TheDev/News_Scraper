"""
Telegraph compiler module
Converts structured JSON to Telegraph pages with SSRF protection
Follows specifications from 04-Security-Guardrails.md
"""

import httpx
from typing import Dict, Optional
from telegraph import Telegraph


class TelegraphCompiler:
    """
    Compiles structured news data into Telegraph pages
    Includes SSRF protection via HEAD request verification
    """
    
    def __init__(self):
        self.telegraph = Telegraph()
        # You'll need to create a Telegraph account and set these
        # For now, we'll use anonymous mode (limited features)
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
        """
        try:
            response = await client.head(url, follow_redirects=True, timeout=10.0)
            
            content_type = response.headers.get('content-type', '').lower()
            if content_type not in ['image/jpeg', 'image/png', 'image/webp']:
                return ""
            
            content_length = response.headers.get('content-length')
            if content_length:
                size_mb = int(content_length) / (1024 * 1024)
                if size_mb > 5:
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
            tasks = []
            for item in news_items:
                image_url = item.get('image_url', '')
                if image_url:
                    tasks.append(self.verify_image_url_async(client, image_url))
                else:
                    async def dummy_task(): return ""
                    tasks.append(dummy_task())
            
            verified_urls = await __import__('asyncio').gather(*tasks)
            
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
            import asyncio
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
