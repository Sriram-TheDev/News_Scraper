"""
Firecrawl integration module
Handles both /scrape (for Digest) and /search (for Live Reporter)
Follows specifications from 02-Architecture-and-Cloud-Ecosystem.md

Fixes applied:
- BUG 8: Uses config.settings instead of raw os.getenv()
- ROOT-FIX-1: Switched from homepage scraping to RSS-based article discovery.
  The old approach scraped homepage URLs and stored them in url_history for dedup.
  Since homepage URLs never change, dedup permanently blocked all future digests.
  Now we discover individual article URLs per source domain via Google News RSS.
"""

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import logging
import base64
import re
import concurrent.futures
from urllib.parse import urlparse
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

    def _extract_domain(self, url: str) -> str:
        """Extract the bare domain from a URL for Google News site: queries."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path
            # Strip www. prefix for cleaner site: queries
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return url

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

    def discover_articles_from_source(self, source_url: str, max_articles: int = 3) -> List[dict]:
        """
        Discover individual article URLs from a source using Google News RSS.
        
        Instead of scraping the source homepage (which yields a static URL that
        poisons deduplication), we query Google News RSS with `site:<domain>` to
        find the latest individual article URLs published on that domain.
        
        Returns a list of dicts: [{'url': '<article_url>', 'title': '<headline>'}]
        """
        domain = self._extract_domain(source_url)
        if not domain or domain == "example.com":
            logger.info(f"Skipping placeholder/invalid source: {source_url}")
            return []

        try:
            encoded_query = urllib.parse.quote(f"site:{domain}")
            req = urllib.request.Request(
                f'https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en',
                headers={'User-Agent': 'Mozilla/5.0 (compatible; JIT-News-Bot/1.0)'}
            )

            raw_xml = urllib.request.urlopen(req, timeout=10.0).read()
            root = ET.fromstring(raw_xml)
            items = root.findall('.//item')

            if not items:
                logger.info(f"No RSS articles found for domain: {domain}")
                return []

            articles = []
            for item in items[:max_articles]:
                title_elem = item.find('title')
                link_elem = item.find('link')

                raw_url = link_elem.text if link_elem is not None else ''
                true_url = self._decode_google_news_url(raw_url)
                title = title_elem.text if title_elem is not None else ''

                if true_url and true_url.startswith('http'):
                    articles.append({'url': true_url, 'title': title})

            logger.info(f"Discovered {len(articles)} articles from {domain}")
            return articles

        except Exception as e:
            logger.warning(f"RSS article discovery failed for {domain}: {str(e)}")
            return []

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

    def scrape_articles_for_digest(self, source_urls: List[str], max_per_source: int = 2) -> List[dict]:
        """
        Discover and scrape individual articles from each source for the daily digest.
        
        This replaces the old `scrape_multiple_urls` which scraped homepage URLs directly.
        Now we:
        1. For each source, discover individual article URLs via Google News RSS 
        2. Collect all unique article URLs across all sources
        3. Scrape each article via Firecrawl concurrently
        4. Return results keyed by individual article URL (enabling proper dedup)
        
        Returns list of dicts: [{'url': '<article_url>', 'markdown': '<content>'}]
        """
        # Step 1: Discover articles from all sources
        all_articles = {}  # url -> title (dedup across sources)
        for source_url in source_urls:
            discovered = self.discover_articles_from_source(source_url, max_articles=max_per_source)
            for article in discovered:
                url = article['url']
                if url not in all_articles:
                    all_articles[url] = article['title']

        if not all_articles:
            logger.warning("No articles discovered from any source via RSS")
            return []

        logger.info(f"Total unique articles discovered: {len(all_articles)}")

        # Step 2: Concurrently scrape all discovered articles
        results = []
        results_lock = __import__('threading').Lock()

        def scrape_article(url_title_pair):
            url, title = url_title_pair
            try:
                markdown = self.scrape_url(url)
                if markdown and markdown.strip():
                    with results_lock:
                        results.append({
                            'url': url,
                            'title': title,
                            'markdown': markdown[:10000]  # Truncate for TPM safety
                        })
                else:
                    logger.warning(f"Empty content scraped for article: {url[:80]}")
            except Exception as e:
                logger.warning(f"Failed to scrape article {url[:80]}: {str(e)}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            executor.map(scrape_article, all_articles.items())

        logger.info(f"Successfully scraped {len(results)} of {len(all_articles)} articles")
        return results

    def scrape_multiple_urls(self, urls: List[str]) -> List[dict]:
        """
        Legacy method - now delegates to scrape_articles_for_digest.
        Kept for backward compatibility with the cron_digest endpoint.
        """
        return self.scrape_articles_for_digest(urls)


# Singleton instance
_scraper_instance: Optional[Scraper] = None


def get_scraper() -> Scraper:
    """Get singleton scraper instance"""
    global _scraper_instance
    if _scraper_instance is None:
        _scraper_instance = Scraper()
    return _scraper_instance
