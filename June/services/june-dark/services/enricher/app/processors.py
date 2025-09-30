"""
Content processors for enrichment
"""

import re
import logging
from typing import Dict, Any, List
from datetime import datetime
from urllib.parse import urlparse
import hashlib

import trafilatura
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class TextProcessor:
    """Process text content and extract entities"""
    
    def __init__(self, db_manager, storage_manager):
        self.db = db_manager
        self.storage = storage_manager
    
    async def process(self, text: str, artifact_id: str, source_url: str) -> Dict[str, Any]:
        """Process text and extract structured data"""
        
        # Extract clean text
        clean_text = self._clean_text(text)
        
        # Extract entities
        urls = self._extract_urls(clean_text)
        emails = self._extract_emails(clean_text)
        phone_numbers = self._extract_phone_numbers(clean_text)
        ip_addresses = self._extract_ips(clean_text)
        domains = self._extract_domains(urls)
        
        # Calculate hash
        text_hash = hashlib.sha256(clean_text.encode()).hexdigest()
        
        result = {
            "artifact_id": artifact_id,
            "source_url": source_url,
            "text": clean_text[:10000],  # Truncate for storage
            "text_length": len(clean_text),
            "text_hash": text_hash,
            "urls": urls,
            "emails": emails,
            "phone_numbers": phone_numbers,
            "ip_addresses": ip_addresses,
            "domains": list(set(domains)),
            "timestamp": datetime.utcnow().isoformat(),
            "indexed_at": datetime.utcnow().isoformat()
        }
        
        return result
    
    def _clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove control characters
        text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
        return text.strip()
    
    def _extract_urls(self, text: str) -> List[str]:
        """Extract URLs from text"""
        url_pattern = r'https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&/=]*)'
        urls = re.findall(url_pattern, text)
        return list(set(urls))[:50]  # Limit to 50 URLs
    
    def _extract_emails(self, text: str) -> List[str]:
        """Extract email addresses from text"""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, text)
        return list(set(emails))[:20]  # Limit to 20 emails
    
    def _extract_phone_numbers(self, text: str) -> List[str]:
        """Extract phone numbers from text"""
        # Simple pattern - enhance for international formats
        phone_pattern = r'\b(?:\+?1[-.]?)?\(?([0-9]{3})\)?[-.]?([0-9]{3})[-.]?([0-9]{4})\b'
        phones = re.findall(phone_pattern, text)
        return ['-'.join(p) for p in phones][:10]
    
    def _extract_ips(self, text: str) -> List[str]:
        """Extract IP addresses from text"""
        ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
        ips = re.findall(ip_pattern, text)
        # Filter valid IPs
        valid_ips = []
        for ip in ips:
            parts = ip.split('.')
            if all(0 <= int(p) <= 255 for p in parts):
                valid_ips.append(ip)
        return list(set(valid_ips))[:20]
    
    def _extract_domains(self, urls: List[str]) -> List[str]:
        """Extract domains from URLs"""
        domains = []
        for url in urls:
            try:
                parsed = urlparse(url)
                if parsed.netloc:
                    domains.append(parsed.netloc)
            except:
                continue
        return list(set(domains))


class MetadataProcessor:
    """Process and extract metadata"""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    async def process(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        """Process artifact metadata"""
        return {
            "artifact_id": artifact["id"],
            "file_type": artifact.get("mime_type"),
            "file_size": artifact.get("file_size"),
            "created_at": artifact.get("created_at"),
            "source_url": artifact.get("source_url")
        }


class AlertProcessor:
    """Check content against watchlists and generate alerts"""
    
    def __init__(self, db_manager):
        self.db = db_manager
        self._watchlists_cache = {}
        self._cache_time = None
    
    async def check_text(
        self,
        text: str,
        artifact_id: str,
        source_url: str
    ) -> List[Dict[str, Any]]:
        """Check text against watchlists"""
        alerts = []
        
        try:
            # Get active watchlists (with simple caching)
            watchlists = await self._get_watchlists()
            
            for watchlist in watchlists:
                if self._check_pattern(text, watchlist):
                    alert = await self._create_alert(
                        watchlist=watchlist,
                        artifact_id=artifact_id,
                        source_url=source_url,
                        matched_text=self._get_context(text, watchlist["pattern"])
                    )
                    alerts.append(alert)
        
        except Exception as e:
            logger.error(f"Error checking alerts: {e}")
        
        return alerts
    
    async def _get_watchlists(self) -> List[Dict[str, Any]]:
        """Get active watchlists from database"""
        # Simple cache for 5 minutes
        now = datetime.utcnow()
        if (not self._cache_time or 
            (now - self._cache_time).seconds > 300):
            
            watchlists = await self.db.pg_fetch(
                "SELECT * FROM watchlists WHERE alert_enabled = true"
            )
            self._watchlists_cache = watchlists
            self._cache_time = now
        
        return self._watchlists_cache
    
    def _check_pattern(self, text: str, watchlist: Dict[str, Any]) -> bool:
        """Check if text matches watchlist pattern"""
        pattern = watchlist["pattern"]
        is_regex = watchlist["is_regex"]
        
        try:
            if is_regex:
                return bool(re.search(pattern, text, re.IGNORECASE))
            else:
                return pattern.lower() in text.lower()
        except Exception as e:
            logger.error(f"Error checking pattern: {e}")
            return False
    
    def _get_context(self, text: str, pattern: str, context_size: int = 100) -> str:
        """Get context around matched pattern"""
        try:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                start = max(0, match.start() - context_size)
                end = min(len(text), match.end() + context_size)
                return text[start:end]
        except:
            pass
        return ""
    
    async def _create_alert(
        self,
        watchlist: Dict[str, Any],
        artifact_id: str,
        source_url: str,
        matched_text: str
    ) -> Dict[str, Any]:
        """Create alert record"""
        alert = {
            "watchlist_id": str(watchlist["id"]),
            "alert_type": watchlist["watchlist_type"],
            "severity": watchlist["priority"],
            "title": f"Match found: {watchlist['name']}",
            "description": f"Pattern '{watchlist['pattern']}' matched in content",
            "artifact_id": artifact_id,
            "source_url": source_url,
            "matched_pattern": watchlist["pattern"],
            "matched_text": matched_text,
            "confidence_score": 0.9,  # Simple confidence
            "status": "new",
            "created_at": datetime.utcnow().isoformat()
        }
        
        # Store in database
        try:
            alert_id = await self.db.pg_fetchval(
                """
                INSERT INTO alerts (
                    watchlist_id, alert_type, severity, title, description,
                    artifact_id, source_url, matched_pattern, confidence_score, status
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
                """,
                watchlist["id"],
                alert["alert_type"],
                alert["severity"],
                alert["title"],
                alert["description"],
                artifact_id,
                source_url,
                alert["matched_pattern"],
                alert["confidence_score"],
                alert["status"]
            )
            alert["id"] = str(alert_id)
        except Exception as e:
            logger.error(f"Error storing alert: {e}")
        
        return alert