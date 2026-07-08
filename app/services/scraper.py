"""
Firecrawl integration module
Handles both /scrape (for Digest) and /search (for Live Reporter)
Follows specifications from 02-Architecture-and-Cloud-Ecosystem.md

Fixes applied:
- BUG 8: Uses config.settings instead of raw os.getenv()
"""

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import logging
from typing import List, Optional
from firecrawl import FirecrawlApp

from app.core.config import settings

logger = logging.getLogger("jit_news_bot")


class Scraper:
    """Firecrawl client for web scraping and search"""

    def __init__(self):
        api_key = settings.firecrawl_api_key
        if not api_key:
            raise ValueError("FIRECRAWL_API_KEY must be set in environment variables")
        self.app = FirecrawlApp(api_key=api_key)

    def scrape_url(self, url: str) -> str:
        """
        Scrape a single URL and return Markdown content
        Used by the Scheduled Lane (Morning Digest)
        """
        try:
            scrape_result = self.app.scrape_url(
                url,
                params={
                    'formats': ['markdown']
                }
            )
            return scrape_result.get('markdown', '')
        except Exception as e:
            raise Exception(f"Firecrawl scrape failed for {url}: {str(e)}")

    def search_query(self, query: str) -> List[dict]:
        """Search for a specific query using Google News RSS for unbreakable live Intel"""
        try:
            encoded_query = urllib.parse.quote(query)
            req = urllib.request.Request(
                f'https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en',
                headers={'User-Agent': 'Mozilla/5.0'}
            )

            raw_xml = urllib.request.urlopen(req, timeout=10.0).read()
            root = ET.fromstring(raw_xml)
            items = root.findall('.//item')

            if not items:
                return []

            results = []
            for item in items[:3]:  # Get top 3 news articles instantly
                title = item.find('title')
                link = item.find('link')

                results.append({
                    'url': link.text if link is not None else '',
                    'title': title.text if title is not None else '',
                    # The title itself contains enough context for the LLM to synthesize the latest breaking news
                    'markdown': f"Live Breaking News Headline: {title.text if title is not None else ''}"
                })
            return results
        except Exception as e:
            raise Exception(f"Live search failed for query '{query}': {str(e)}")

    def scrape_multiple_urls(self, urls: List[str]) -> List[dict]:
        """
        Scrape multiple URLs (for Digest lane)
        Returns list of dicts with url and markdown content.
        Only returns items with actual content (empty/failed scrapes are filtered out).
        """
        results = []
        for url in urls:
            try:
                markdown = self.scrape_url(url)
                if markdown and markdown.strip():
                    results.append({
                        'url': url,
                        'markdown': markdown
                    })
                else:
                    logger.warning(f"Scrape returned empty content for {url}, skipping")
            except Exception as e:
                # BUG 5 FIX: Log error but do NOT append items with empty markdown.
                # Previously, failed scrapes were still appended with empty markdown,
                # causing the LLM to receive empty payloads and hallucinate.
                logger.warning(f"Failed to scrape {url}: {str(e)}")
        return results


# Singleton instance
_scraper_instance: Optional[Scraper] = None


def get_scraper() -> Scraper:
    """Get singleton scraper instance"""
    global _scraper_instance
    if _scraper_instance is None:
        _scraper_instance = Scraper()
    return _scraper_instance
