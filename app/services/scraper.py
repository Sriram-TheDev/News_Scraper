"""
Firecrawl integration module
Handles both /scrape (for Digest) and /search (for Live Reporter)
Follows specifications from 02-Architecture-and-Cloud-Ecosystem.md
"""

import os
from typing import List, Optional
from firecrawl import FirecrawlApp
from dotenv import load_dotenv

load_dotenv()


class Scraper:
    """Firecrawl client for web scraping and search"""
    
    def __init__(self):
        api_key = os.getenv("FIRECRAWL_API_KEY")
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
        """Search for a specific query by using duckduckgo-search bypass module"""
        from duckduckgo_search import DDGS
        
        try:
            results = []
            # Fetch top 3 results using native anti-bot wrapper
            search_results = DDGS().text(query, max_results=3)
            
            if not search_results:
                return []
                
            for item in search_results:
                results.append({
                    'url': item.get('href', ''),
                    'title': item.get('title', ''),
                    'markdown': item.get('body', '')
                })
            return results
        except Exception as e:
            raise Exception(f"Live search failed for query '{query}': {str(e)}")
    
    def scrape_multiple_urls(self, urls: List[str]) -> List[dict]:
        """
        Scrape multiple URLs (for Digest lane)
        Returns list of dicts with url and markdown content
        """
        results = []
        for url in urls:
            try:
                markdown = self.scrape_url(url)
                results.append({
                    'url': url,
                    'markdown': markdown
                })
            except Exception as e:
                # Log error but continue with other URLs
                print(f"Failed to scrape {url}: {str(e)}")
                results.append({
                    'url': url,
                    'markdown': '',
                    'error': str(e)
                })
        return results


# Singleton instance
_scraper_instance: Optional[Scraper] = None


def get_scraper() -> Scraper:
    """Get singleton scraper instance"""
    global _scraper_instance
    if _scraper_instance is None:
        _scraper_instance = Scraper()
    return _scraper_instance
