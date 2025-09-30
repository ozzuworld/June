"""
Web Crawler using Playwright
"""

import asyncio
import logging
import hashlib
import mimetypes
from urllib.parse import urljoin, urlparse
from datetime import datetime
from typing import Set, Dict, Any, List
from io import BytesIO

from playwright.async_api import async_playwright, Browser, Page
from bs4 import BeautifulSoup
import trafilatura
from PIL import Image

from config import settings

logger = logging.getLogger(__name__)


class WebCrawler:
    """Async web crawler with Playwright"""
    
    def __init__(self, storage_manager, redis_client):
        self.storage = storage_manager
        self.redis = redis_client
        self.browser: Browser = None
        self.playwright = None
        self.visited_urls: Set[str] = set()
    
    async def initialize(self):
        """Initialize Playwright browser"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        logger.info("✓ Playwright browser initialized")
    
    async def close(self):
        """Close browser and playwright"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("✓ Browser closed")
    
    async def crawl_domain(
        self,
        domain: str,
        max_depth: int = 2,
        job_id: str = None
    ) -> Dict[str, Any]:
        """
        Crawl a domain and collect artifacts
        
        Returns:
            Dict with success status, pages crawled, and artifacts collected
        """
        self.visited_urls.clear()
        
        result = {
            "success": False,
            "domain": domain,
            "pages_crawled": 0,
            "artifacts_collected": 0,
            "errors": []
        }
        
        try:
            # Start URL
            start_url = f"https://{domain}" if not domain.startswith("http") else domain
            
            # Crawl recursively
            await self._crawl_recursive(
                url=start_url,
                domain=domain,
                depth=0,
                max_depth=max_depth,
                job_id=job_id,
                result=result
            )
            
            result["success"] = True
        
        except Exception as e:
            logger.error(f"Crawl failed for {domain}: {e}")
            result["error"] = str(e)
        
        return result
    
    async def _crawl_recursive(
        self,
        url: str,
        domain: str,
        depth: int,
        max_depth: int,
        job_id: str,
        result: Dict[str, Any]
    ):
        """Recursively crawl pages"""
        
        # Check limits
        if depth > max_depth:
            return
        
        if url in self.visited_urls:
            return
        
        if result["pages_crawled"] >= settings.MAX_PAGES_PER_DOMAIN:
            return
        
        # Check if same domain
        parsed = urlparse(url)
        if domain not in parsed.netloc:
            return
        
        # Mark as visited
        self.visited_urls.add(url)
        result["pages_crawled"] += 1
        
        logger.info(f"Crawling [{depth}/{max_depth}]: {url}")
        
        try:
            # Create new page
            context = await self.browser.new_context(
                user_agent=settings.USER_AGENT,
                viewport={
                    'width': settings.SCREENSHOT_WIDTH,
                    'height': settings.SCREENSHOT_HEIGHT
                }
            )
            page = await context.new_page()
            
            # Navigate
            await page.goto(url, timeout=settings.REQUEST_TIMEOUT * 1000)
            await page.wait_for_load_state('networkidle', timeout=10000)
            
            # Extract content
            artifacts = await self._extract_page_content(page, url, job_id)
            result["artifacts_collected"] += len(artifacts)
            
            # Extract links for deeper crawling
            if depth < max_depth:
                links = await self._extract_links(page, url, domain)
                
                # Crawl next level with delay
                for link in links[:10]:  # Limit links per page
                    await asyncio.sleep(settings.DOWNLOAD_DELAY)
                    await self._crawl_recursive(
                        link, domain, depth + 1, max_depth, job_id, result
                    )
            
            # Close page
            await page.close()
            await context.close()
        
        except Exception as e:
            logger.error(f"Error crawling {url}: {e}")
            result["errors"].append({"url": url, "error": str(e)})
    
    async def _extract_page_content(
        self,
        page: Page,
        url: str,
        job_id: str
    ) -> List[Dict[str, Any]]:
        """Extract and store page content"""
        artifacts = []
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        
        try:
            # Get HTML
            html = await page.content()
            
            # Extract text with trafilatura
            text = trafilatura.extract(html)
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(html, 'lxml')
            
            # Extract metadata
            metadata = {
                "url": url,
                "title": await page.title(),
                "timestamp": datetime.utcnow().isoformat(),
                "job_id": job_id
            }
            
            # Store HTML
            html_path = f"html/{timestamp}_{url_hash}.html"
            self.storage.upload_data(
                settings.BUCKET_ARTIFACTS,
                html_path,
                html.encode('utf-8'),
                content_type="text/html"
            )
            artifacts.append({
                "type": "html",
                "path": html_path,
                "size": len(html)
            })
            
            # Store extracted text
            if text and settings.EXTRACT_TEXT:
                text_path = f"text/{timestamp}_{url_hash}.txt"
                self.storage.upload_data(
                    settings.BUCKET_ARTIFACTS,
                    text_path,
                    text.encode('utf-8'),
                    content_type="text/plain"
                )
                artifacts.append({
                    "type": "text",
                    "path": text_path,
                    "size": len(text)
                })
            
            # Take screenshot
            if settings.SCREENSHOT_ENABLED:
                screenshot_bytes = await page.screenshot(
                    full_page=True,
                    type='jpeg',
                    quality=settings.SCREENSHOT_QUALITY
                )
                
                screenshot_path = f"screenshots/{timestamp}_{url_hash}.jpg"
                self.storage.upload_data(
                    settings.BUCKET_ARTIFACTS,
                    screenshot_path,
                    screenshot_bytes,
                    content_type="image/jpeg"
                )
                artifacts.append({
                    "type": "screenshot",
                    "path": screenshot_path,
                    "size": len(screenshot_bytes)
                })
            
            # Extract images
            if settings.EXTRACT_IMAGES:
                images = await self._extract_images(soup, url, timestamp, url_hash)
                artifacts.extend(images)
            
            # Store metadata
            import json
            metadata_path = f"metadata/{timestamp}_{url_hash}.json"
            self.storage.upload_data(
                settings.BUCKET_ARTIFACTS,
                metadata_path,
                json.dumps(metadata, indent=2).encode('utf-8'),
                content_type="application/json"
            )
            
            logger.info(f"✓ Extracted {len(artifacts)} artifacts from {url}")
        
        except Exception as e:
            logger.error(f"Error extracting content from {url}: {e}")
        
        return artifacts
    
    async def _extract_links(
        self,
        page: Page,
        base_url: str,
        domain: str
    ) -> List[str]:
        """Extract all links from page"""
        links = []
        
        try:
            # Get all links
            elements = await page.query_selector_all('a[href]')
            
            for element in elements:
                href = await element.get_attribute('href')
                if href:
                    # Resolve relative URLs
                    absolute_url = urljoin(base_url, href)
                    parsed = urlparse(absolute_url)
                    
                    # Only same domain, http/https
                    if (domain in parsed.netloc and 
                        parsed.scheme in ['http', 'https'] and
                        absolute_url not in self.visited_urls):
                        links.append(absolute_url)
        
        except Exception as e:
            logger.error(f"Error extracting links: {e}")
        
        return links
    
    async def _extract_images(
        self,
        soup: BeautifulSoup,
        base_url: str,
        timestamp: str,
        url_hash: str
    ) -> List[Dict[str, Any]]:
        """Extract images from page"""
        images = []
        
        try:
            img_tags = soup.find_all('img', src=True)
            
            for idx, img in enumerate(img_tags[:5]):  # Limit to 5 images per page
                try:
                    img_url = urljoin(base_url, img['src'])
                    
                    # Download image (simplified - use requests in real implementation)
                    import httpx
                    async with httpx.AsyncClient() as client:
                        response = await client.get(img_url, timeout=10)
                        
                        if response.status_code == 200:
                            img_data = response.content
                            
                            # Determine extension
                            content_type = response.headers.get('content-type', '')
                            ext = mimetypes.guess_extension(content_type) or '.jpg'
                            
                            # Store image
                            img_path = f"images/{timestamp}_{url_hash}_{idx}{ext}"
                            self.storage.upload_data(
                                settings.BUCKET_ARTIFACTS,
                                img_path,
                                img_data,
                                content_type=content_type or 'image/jpeg'
                            )
                            
                            images.append({
                                "type": "image",
                                "path": img_path,
                                "size": len(img_data),
                                "source_url": img_url
                            })
                
                except Exception as e:
                    logger.debug(f"Failed to download image: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Error extracting images: {e}")
        
        return images