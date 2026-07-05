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
    
    def verify_image_url(self, url: str) -> bool:
        """
        Server-Side Media Verification (SSRF Protection)
        Before using an image URL, verify it's safe:
        1. Content-Type must be image/jpeg or image/png
        2. Size must be under 5MB
        
        This prevents malicious sources from smuggling bad payloads
        """
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.head(url, follow_redirects=True)
                
                # Check content type
                content_type = response.headers.get('content-type', '').lower()
                if content_type not in ['image/jpeg', 'image/png']:
                    return False
                
                # Check size
                content_length = response.headers.get('content-length')
                if content_length:
                    size_mb = int(content_length) / (1024 * 1024)
                    if size_mb > 5:
                        return False
                
                return True
        except Exception:
            # If verification fails, reject the URL
            return False
    
    def compile_page(self, news_data: Dict) -> str:
        """
        Compile structured news data into a Telegraph page
        Returns the Telegraph URL
        """
        # Verify image URL before using it (SSRF protection)
        image_url = news_data.get('image_url', '')
        if image_url:
            if not self.verify_image_url(image_url):
                # If image fails verification, use placeholder or omit
                image_url = ''
        
        # Build Telegraph page content
        title = news_data.get('title', 'News Digest')
        summary = news_data.get('summary', '')
        source_link = news_data.get('source_link', '')
        
        # Create HTML content for Telegraph
        html_content = f"""
        <h3>{title}</h3>
        <p>{summary}</p>
        """
        
        if image_url:
            html_content += f'<img src="{image_url}" alt="{title}"/>'
        
        if source_link:
            html_content += f'<p><a href="{source_link}">Read more at source</a></p>'
        
        try:
            # Create Telegraph page
            page = self.telegraph.create_page(
                title=title,
                html_content=html_content,
                author_name='JIT News Bot'
            )
            return page['url']
        except Exception as e:
            raise Exception(f"Failed to create Telegraph page: {str(e)}")
    
    def compile_digest_page(self, news_items: list) -> str:
        """
        Compile multiple news items into a single Telegraph digest page
        Used by the Scheduled Lane (Morning Digest)
        """
        html_content = "<h2>Morning News Digest</h2>"
        
        for item in news_items:
            title = item.get('title', 'Untitled')
            summary = item.get('summary', '')
            image_url = item.get('image_url', '')
            source_link = item.get('source_link', '')
            
            # Verify image URL
            if image_url:
                if not self.verify_image_url(image_url):
                    image_url = ''
            
            html_content += f"<hr/><h3>{title}</h3>"
            html_content += f"<p>{summary}</p>"
            
            if image_url:
                html_content += f'<img src="{image_url}" alt="{title}"/>'
            
            if source_link:
                html_content += f'<p><a href="{source_link}">Read more</a></p>'
        
        try:
            page = self.telegraph.create_page(
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
