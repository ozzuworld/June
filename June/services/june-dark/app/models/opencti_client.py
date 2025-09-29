from pycti import OpenCTIApiClient
from typing import Dict, List, Any, Optional, Union
import logging
import asyncio
from datetime import datetime, timezone
import uuid
import json

logger = logging.getLogger(__name__)

class OpenCTIClient:
    """OpenCTI API client for threat intelligence integration"""
    
    # Indicator types for OSINT analysis
    INDICATOR_TYPES = {
        'file': 'File',
        'url': 'Url',
        'domain': 'Domain-Name',
        'ipv4': 'IPv4-Addr',
        'ipv6': 'IPv6-Addr',
        'email': 'Email-Addr',
        'hash_md5': 'File',
        'hash_sha1': 'File',
        'hash_sha256': 'File',
        'user_agent': 'User-Agent',
        'registry_key': 'Windows-Registry-Key',
        'mutex': 'Mutex',
        'artifact': 'Artifact'
    }
    
    # Threat levels mapping
    THREAT_LEVELS = {
        'unknown': 0,
        'white': 10,
        'green': 20,
        'yellow': 50,
        'orange': 75,
        'red': 85,
        'black': 95
    }
    
    def __init__(self, url: str, token: str, verify_ssl: bool = True):
        self.url = url
        self.token = token
        self.verify_ssl = verify_ssl
        self.client: Optional[OpenCTIApiClient] = None
        self.connected = False
        
        logger.info(f"OpenCTI client initialized for: {url}")
    
    async def connect(self) -> bool:
        """Establish connection to OpenCTI"""
        try:
            # Initialize client in executor to avoid blocking
            loop = asyncio.get_event_loop()
            self.client = await loop.run_in_executor(
                None,
                self._create_client
            )
            
            # Test connection
            about_info = await loop.run_in_executor(
                None,
                self.client.get_about
            )
            
            self.connected = True
            logger.info(f"Connected to OpenCTI: {about_info.get('version', 'unknown')}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to OpenCTI: {str(e)}")
            self.connected = False
            return False
    
    def _create_client(self) -> OpenCTIApiClient:
        """Create OpenCTI API client synchronously"""
        return OpenCTIApiClient(
            url=self.url,
            token=self.token,
            ssl_verify=self.verify_ssl,
            log_level='WARNING'  # Reduce log verbosity
        )
    
    async def disconnect(self) -> None:
        """Disconnect from OpenCTI"""
        self.connected = False
        self.client = None
        logger.info("Disconnected from OpenCTI")
    
    async def is_connected(self) -> bool:
        """Check if connected to OpenCTI"""
        if not self.connected or not self.client:
            return False
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self.client.get_about
            )
            return True
        except Exception:
            self.connected = False
            return False
    
    async def create_indicator(
        self,
        pattern: str,
        indicator_type: str,
        labels: List[str],
        confidence: int = 50,
        description: str = "",
        source: str = "June Dark OSINT",
        tlp_marking: str = "TLP:GREEN"
    ) -> Optional[Dict[str, Any]]:
        """Create a new indicator in OpenCTI"""
        if not self.connected:
            raise RuntimeError("Not connected to OpenCTI")
        
        try:
            # Map indicator type
            opencti_type = self.INDICATOR_TYPES.get(indicator_type.lower())
            if not opencti_type:
                logger.warning(f"Unsupported indicator type: {indicator_type}")
                return None
            
            # Prepare indicator data
            indicator_data = {
                'pattern': pattern,
                'pattern_type': 'stix',
                'main_observable_type': opencti_type,
                'labels': labels,
                'confidence': confidence,
                'description': description or f"OSINT indicator from {source}",
                'created_by_ref': source,
                'object_marking_refs': [tlp_marking],
                'valid_from': datetime.now(timezone.utc).isoformat(),
                'kill_chain_phases': []
            }
            
            # Create indicator
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self.client.indicator.create,
                indicator_data
            )
            
            logger.info(f"Created indicator: {pattern} (ID: {result.get('id')})")
            return result
            
        except Exception as e:
            logger.error(f"Failed to create indicator: {str(e)}")
            return None
    
    async def search_indicators(
        self,
        filters: Dict[str, Any] = None,
        search: str = None,
        first: int = 10
    ) -> List[Dict[str, Any]]:
        """Search for indicators in OpenCTI"""
        if not self.connected:
            raise RuntimeError("Not connected to OpenCTI")
        
        try:
            search_filters = filters or {}
            if search:
                search_filters['search'] = search
            
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                self.client.indicator.list,
                first,
                **search_filters
            )
            
            logger.debug(f"Found {len(results)} indicators")
            return results
            
        except Exception as e:
            logger.error(f"Failed to search indicators: {str(e)}")
            return []
    
    async def create_observable(
        self,
        observable_type: str,
        observable_value: str,
        labels: List[str] = None,
        confidence: int = 50,
        description: str = ""
    ) -> Optional[Dict[str, Any]]:
        """Create an observable in OpenCTI"""
        if not self.connected:
            raise RuntimeError("Not connected to OpenCTI")
        
        try:
            # Map observable type
            opencti_type = self.INDICATOR_TYPES.get(observable_type.lower())
            if not opencti_type:
                logger.warning(f"Unsupported observable type: {observable_type}")
                return None
            
            observable_data = {
                'type': opencti_type,
                'observable_value': observable_value,
                'labels': labels or [],
                'confidence': confidence,
                'description': description
            }
            
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self.client.stix_cyber_observable.create,
                observable_data
            )
            
            logger.info(f"Created observable: {observable_value} (ID: {result.get('id')})")
            return result
            
        except Exception as e:
            logger.error(f"Failed to create observable: {str(e)}")
            return None
    
    async def create_report(
        self,
        name: str,
        description: str,
        published: datetime,
        objects: List[str] = None,
        labels: List[str] = None,
        confidence: int = 50
    ) -> Optional[Dict[str, Any]]:
        """Create a report in OpenCTI"""
        if not self.connected:
            raise RuntimeError("Not connected to OpenCTI")
        
        try:
            report_data = {
                'name': name,
                'description': description,
                'published': published.isoformat(),
                'report_types': ['threat-report'],
                'labels': labels or [],
                'confidence': confidence,
                'object_refs': objects or [],
                'created_by_ref': 'June Dark OSINT'
            }
            
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self.client.report.create,
                report_data
            )
            
            logger.info(f"Created report: {name} (ID: {result.get('id')})")
            return result
            
        except Exception as e:
            logger.error(f"Failed to create report: {str(e)}")
            return None
    
    async def enrich_with_context(
        self,
        indicator_value: str,
        indicator_type: str
    ) -> Dict[str, Any]:
        """Enrich indicator with existing OpenCTI context"""
        if not self.connected:
            return {"enriched": False, "context": None}
        
        try:
            # Search for existing indicators
            existing = await self.search_indicators(
                filters={"pattern": indicator_value},
                first=5
            )
            
            if not existing:
                return {"enriched": False, "context": None}
            
            # Extract relevant context
            context = {
                "existing_indicators": len(existing),
                "labels": [],
                "confidence_scores": [],
                "sources": [],
                "last_seen": None,
                "threat_level": "unknown"
            }
            
            for indicator in existing:
                if indicator.get('labels'):
                    context['labels'].extend(indicator['labels'])
                
                if indicator.get('confidence'):
                    context['confidence_scores'].append(indicator['confidence'])
                
                if indicator.get('created_by_ref'):
                    context['sources'].append(indicator['created_by_ref'])
                
                if indicator.get('modified'):
                    if not context['last_seen'] or indicator['modified'] > context['last_seen']:
                        context['last_seen'] = indicator['modified']
            
            # Calculate threat level from confidence scores
            if context['confidence_scores']:
                avg_confidence = sum(context['confidence_scores']) / len(context['confidence_scores'])
                if avg_confidence >= 80:
                    context['threat_level'] = 'high'
                elif avg_confidence >= 60:
                    context['threat_level'] = 'medium'
                else:
                    context['threat_level'] = 'low'
            
            # Remove duplicates
            context['labels'] = list(set(context['labels']))
            context['sources'] = list(set(context['sources']))
            
            return {"enriched": True, "context": context}
            
        except Exception as e:
            logger.error(f"Failed to enrich indicator: {str(e)}")
            return {"enriched": False, "error": str(e)}
    
    async def bulk_create_indicators(
        self,
        indicators: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Create multiple indicators efficiently"""
        if not self.connected:
            raise RuntimeError("Not connected to OpenCTI")
        
        results = {
            "success_count": 0,
            "error_count": 0,
            "created_ids": [],
            "errors": []
        }
        
        for indicator_data in indicators:
            try:
                result = await self.create_indicator(**indicator_data)
                if result:
                    results["success_count"] += 1
                    results["created_ids"].append(result.get('id'))
                else:
                    results["error_count"] += 1
                    
            except Exception as e:
                results["error_count"] += 1
                results["errors"].append({
                    "pattern": indicator_data.get("pattern", "unknown"),
                    "error": str(e)
                })
        
        logger.info(
            f"Bulk indicator creation: {results['success_count']} success, "
            f"{results['error_count']} errors"
        )
        
        return results
    
    async def get_statistics(self) -> Dict[str, Any]:
        """Get OpenCTI instance statistics"""
        if not self.connected:
            return {"connected": False}
        
        try:
            loop = asyncio.get_event_loop()
            
            # Get basic statistics
            about = await loop.run_in_executor(None, self.client.get_about)
            
            # Count indicators
            indicators_count = len(await self.search_indicators(first=1000))
            
            stats = {
                "connected": True,
                "version": about.get('version', 'unknown'),
                "indicators_count": indicators_count,
                "url": self.url,
                "last_check": datetime.now().isoformat()
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get OpenCTI statistics: {str(e)}")
            return {"connected": False, "error": str(e)}
    
    def get_client_info(self) -> Dict[str, Any]:
        """Get client configuration information"""
        return {
            "url": self.url,
            "connected": self.connected,
            "verify_ssl": self.verify_ssl,
            "supported_indicators": list(self.INDICATOR_TYPES.keys()),
            "threat_levels": list(self.THREAT_LEVELS.keys())
        }