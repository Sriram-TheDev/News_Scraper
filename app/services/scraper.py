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
import base64
import re
import concurrent.futures
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

    def _decode_google_news_url(self, raw_url: str) -> str:
        """
        Reverse-engineers and decodes the hidden naked URL from a Google News RSS link.
        Google uses a Base64-like wrapper under 'articles/CBMi...'.
        """
        try:
            if '/articles/' not in raw_url:
                return raw_url
                
            hash_part = raw_url.split('/articles/')[-1].split('?')[0]
            # Ensure proper padding for base64
            padding_needed = len(hash_part) % 4
            if padding_needed:
                hash_part += '=' * (4 - padding_needed)
                
            # Use URL-safe base64 decoding and decode with a permissive encoding
            decoded_bytes = base64.urlsafe_b64decode(hash_part)
            decoded_str = decoded_bytes.decode('latin1', errors='ignore')
            
            # Regex out the actual http/https URL from the protobuf noise
            match = re.search(r'https?://[^\s\x00-\x1F]+', decoded_str)
            if match:
                return match.group(0)
            return raw_url
        except Exception as e:
            logger.warning(f"Failed to decode Google News URL {raw_url}: {str(e)}")
            return raw_url

    def scrape_url(self, url: str) -> str:
        """
        Scrape a single URL and return Markdown content
        Used by the Scheduled Lane (Morning Digest) and Live Reporter
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
        """Search for a specific query using Google News RSS, decode actual links, and deeply scrape in parallel"""
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
            
            # Step 1: Decode URLs to bypass Google JS redirects
            for item in items[:3]:
                title_elem = item.find('title')
                link_elem = item.find('link')
                
                raw_url = link_elem.text if link_elem is not None else ''
                true_url = self._decode_google_news_url(raw_url)
                
                results.append({
                    'url': true_url,
                    'title': title_elem.text if title_elem is not None else '',
                    'markdown': '' # will be populated below
                })
                
            # Step 2: Concurrently scrape full content for the decoded URLs
            def fetch_content(result_dict):
                try:
                    if result_dict['url']:
                        md = self.scrape_url(result_dict['url'])
                        if md and md.strip():
                            # Defensively truncate to ~8000 characters (~2000 tokens) per article to stay well below Groq's 12k TPM free tier limit
                            result_dict['markdown'] = f"Headline: {result_dict['title']}\n\n{md[:8000]}"
                            return
                except Exception as e:
                    logger.warning(f"Live search deep scrape failed for {result_dict['url']}: {str(e)}")
                # Fallback to headline only if scrape fails
                result_dict['markdown'] = f"Headline: {result_dict['title']} (Full content could not be scraped)"

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                executor.map(fetch_content, results)

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
