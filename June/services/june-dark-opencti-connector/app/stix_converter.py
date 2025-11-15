"""
Convert June Dark enriched data to STIX 2.1 format
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from uuid import uuid4

from stix2 import (
    Identity, Indicator, Relationship, ObservedData, DomainName,
    IPv4Address, IPv6Address, URL, EmailAddress, Bundle,
    Note, Report, Incident, TLP_WHITE, TLP_GREEN, TLP_AMBER
)
from pycti import OpenCTIConnectorHelper

from .config import settings

logger = logging.getLogger(__name__)


class STIXConverter:
    """Convert June Dark data to STIX 2.1 objects"""

    def __init__(self, helper: OpenCTIConnectorHelper):
        self.helper = helper
        self.author = self._create_author()
        self.tlp_mapping = {
            "white": TLP_WHITE,
            "green": TLP_GREEN,
            "amber": TLP_AMBER,
        }

    def _create_author(self) -> Identity:
        """Create identity for the June Dark framework"""
        return Identity(
            id=f"identity--{uuid4()}",
            name=settings.AUTHOR_NAME,
            identity_class="system",
            created=datetime.utcnow(),
            modified=datetime.utcnow()
        )

    def convert_enriched_data(self, data: Dict[str, Any]) -> Bundle:
        """Convert enriched data to STIX bundle"""

        stix_objects = [self.author]

        try:
            # Extract metadata
            artifact_id = data.get("artifact_id")
            source_url = data.get("source_url")
            timestamp = data.get("timestamp", datetime.utcnow().isoformat())

            # Convert URLs to observables
            if settings.MAP_URLS_AS_OBSERVABLES and data.get("urls"):
                url_objects = self._create_url_observables(
                    data["urls"],
                    artifact_id,
                    timestamp
                )
                stix_objects.extend(url_objects)

            # Convert IPs to observables
            if settings.MAP_IPS_AS_OBSERVABLES and data.get("ip_addresses"):
                ip_objects = self._create_ip_observables(
                    data["ip_addresses"],
                    artifact_id,
                    timestamp
                )
                stix_objects.extend(ip_objects)

            # Convert domains to observables
            if settings.MAP_DOMAINS_AS_OBSERVABLES and data.get("domains"):
                domain_objects = self._create_domain_observables(
                    data["domains"],
                    artifact_id,
                    timestamp
                )
                stix_objects.extend(domain_objects)

            # Convert emails to observables
            if settings.MAP_EMAILS_AS_OBSERVABLES and data.get("emails"):
                email_objects = self._create_email_observables(
                    data["emails"],
                    artifact_id,
                    timestamp
                )
                stix_objects.extend(email_objects)

            # Create note with full content
            if settings.CREATE_NOTES and data.get("text"):
                note = self._create_note(data, artifact_id, timestamp)
                stix_objects.append(note)

            # Create report summarizing findings
            if settings.CREATE_REPORTS and len(stix_objects) > 1:
                report = self._create_report(
                    data,
                    [obj.id for obj in stix_objects if obj != self.author],
                    timestamp
                )
                stix_objects.append(report)

            logger.info(f"Created STIX bundle with {len(stix_objects)} objects for {artifact_id}")

            return Bundle(objects=stix_objects, allow_custom=True)

        except Exception as e:
            logger.error(f"Error converting data to STIX: {e}", exc_info=True)
            raise

    def convert_alert(self, alert: Dict[str, Any]) -> Bundle:
        """Convert June Dark alert to STIX incident"""

        stix_objects = [self.author]

        try:
            timestamp = alert.get("created_at", datetime.utcnow().isoformat())

            # Create incident
            incident = Incident(
                id=f"incident--{uuid4()}",
                name=alert.get("title", "Alert from June Dark"),
                description=alert.get("description", ""),
                created=timestamp,
                modified=timestamp,
                created_by_ref=self.author.id,
                confidence=alert.get("confidence_score", 75),
                labels=["osint", "june-dark", alert.get("alert_type", "unknown")],
                severity=self._map_severity(alert.get("severity", "medium")),
                source=settings.SOURCE_NAME,
                external_references=[{
                    "source_name": "June Dark",
                    "url": alert.get("source_url", ""),
                    "description": f"Matched pattern: {alert.get('matched_pattern', '')}"
                }]
            )
            stix_objects.append(incident)

            # Add note with matched text
            if alert.get("matched_text"):
                note = Note(
                    id=f"note--{uuid4()}",
                    content=f"Matched text: {alert['matched_text']}",
                    created=timestamp,
                    modified=timestamp,
                    created_by_ref=self.author.id,
                    object_refs=[incident.id]
                )
                stix_objects.append(note)

            logger.info(f"Created STIX incident for alert: {alert.get('title')}")

            return Bundle(objects=stix_objects, allow_custom=True)

        except Exception as e:
            logger.error(f"Error converting alert to STIX: {e}", exc_info=True)
            raise

    def _create_url_observables(
        self,
        urls: List[str],
        artifact_id: str,
        timestamp: str
    ) -> List:
        """Create URL observables"""

        objects = []
        for url in urls[:50]:  # Limit to 50 URLs
            try:
                url_obj = URL(value=url)

                observed_data = ObservedData(
                    id=f"observed-data--{uuid4()}",
                    created=timestamp,
                    modified=timestamp,
                    first_observed=timestamp,
                    last_observed=timestamp,
                    number_observed=1,
                    created_by_ref=self.author.id,
                    objects={"0": url_obj},
                    labels=["june-dark", "osint", "url"],
                    external_references=[{
                        "source_name": "June Dark",
                        "description": f"Extracted from artifact {artifact_id}"
                    }]
                )
                objects.append(observed_data)

                # Create indicator if enabled
                if settings.CREATE_INDICATORS:
                    indicator = Indicator(
                        id=f"indicator--{uuid4()}",
                        created=timestamp,
                        modified=timestamp,
                        created_by_ref=self.author.id,
                        name=f"URL: {url[:100]}",
                        description=f"URL discovered by June Dark OSINT",
                        pattern=f"[url:value = '{url}']",
                        pattern_type="stix",
                        valid_from=timestamp,
                        labels=["osint", "url"],
                        confidence=settings.CONNECTOR_CONFIDENCE_LEVEL
                    )
                    objects.append(indicator)

                    # Create relationship
                    relationship = Relationship(
                        id=f"relationship--{uuid4()}",
                        created=timestamp,
                        modified=timestamp,
                        relationship_type="based-on",
                        source_ref=indicator.id,
                        target_ref=observed_data.id
                    )
                    objects.append(relationship)

            except Exception as e:
                logger.warning(f"Failed to create observable for URL {url}: {e}")
                continue

        return objects

    def _create_ip_observables(
        self,
        ips: List[str],
        artifact_id: str,
        timestamp: str
    ) -> List:
        """Create IP observables"""

        objects = []
        for ip in ips[:50]:
            try:
                # Determine if IPv4 or IPv6
                if ":" in ip:
                    ip_obj = IPv6Address(value=ip)
                else:
                    ip_obj = IPv4Address(value=ip)

                observed_data = ObservedData(
                    id=f"observed-data--{uuid4()}",
                    created=timestamp,
                    modified=timestamp,
                    first_observed=timestamp,
                    last_observed=timestamp,
                    number_observed=1,
                    created_by_ref=self.author.id,
                    objects={"0": ip_obj},
                    labels=["june-dark", "osint", "ip"],
                    external_references=[{
                        "source_name": "June Dark",
                        "description": f"Extracted from artifact {artifact_id}"
                    }]
                )
                objects.append(observed_data)

                if settings.CREATE_INDICATORS:
                    indicator = Indicator(
                        id=f"indicator--{uuid4()}",
                        created=timestamp,
                        modified=timestamp,
                        created_by_ref=self.author.id,
                        name=f"IP Address: {ip}",
                        description="IP address discovered by June Dark OSINT",
                        pattern=f"[ipv4-addr:value = '{ip}']" if "." in ip else f"[ipv6-addr:value = '{ip}']",
                        pattern_type="stix",
                        valid_from=timestamp,
                        labels=["osint", "ip"],
                        confidence=settings.CONNECTOR_CONFIDENCE_LEVEL
                    )
                    objects.append(indicator)

            except Exception as e:
                logger.warning(f"Failed to create observable for IP {ip}: {e}")
                continue

        return objects

    def _create_domain_observables(
        self,
        domains: List[str],
        artifact_id: str,
        timestamp: str
    ) -> List:
        """Create domain observables"""

        objects = []
        for domain in domains[:50]:
            try:
                domain_obj = DomainName(value=domain)

                observed_data = ObservedData(
                    id=f"observed-data--{uuid4()}",
                    created=timestamp,
                    modified=timestamp,
                    first_observed=timestamp,
                    last_observed=timestamp,
                    number_observed=1,
                    created_by_ref=self.author.id,
                    objects={"0": domain_obj},
                    labels=["june-dark", "osint", "domain"],
                    external_references=[{
                        "source_name": "June Dark",
                        "description": f"Extracted from artifact {artifact_id}"
                    }]
                )
                objects.append(observed_data)

                if settings.CREATE_INDICATORS:
                    indicator = Indicator(
                        id=f"indicator--{uuid4()}",
                        created=timestamp,
                        modified=timestamp,
                        created_by_ref=self.author.id,
                        name=f"Domain: {domain}",
                        description="Domain discovered by June Dark OSINT",
                        pattern=f"[domain-name:value = '{domain}']",
                        pattern_type="stix",
                        valid_from=timestamp,
                        labels=["osint", "domain"],
                        confidence=settings.CONNECTOR_CONFIDENCE_LEVEL
                    )
                    objects.append(indicator)

            except Exception as e:
                logger.warning(f"Failed to create observable for domain {domain}: {e}")
                continue

        return objects

    def _create_email_observables(
        self,
        emails: List[str],
        artifact_id: str,
        timestamp: str
    ) -> List:
        """Create email observables"""

        objects = []
        for email in emails[:30]:
            try:
                email_obj = EmailAddress(value=email)

                observed_data = ObservedData(
                    id=f"observed-data--{uuid4()}",
                    created=timestamp,
                    modified=timestamp,
                    first_observed=timestamp,
                    last_observed=timestamp,
                    number_observed=1,
                    created_by_ref=self.author.id,
                    objects={"0": email_obj},
                    labels=["june-dark", "osint", "email"],
                    external_references=[{
                        "source_name": "June Dark",
                        "description": f"Extracted from artifact {artifact_id}"
                    }]
                )
                objects.append(observed_data)

            except Exception as e:
                logger.warning(f"Failed to create observable for email {email}: {e}")
                continue

        return objects

    def _create_note(
        self,
        data: Dict[str, Any],
        artifact_id: str,
        timestamp: str
    ) -> Note:
        """Create note with extracted content"""

        content = f"""
# June Dark OSINT Report

**Source**: {data.get('source_url', 'Unknown')}
**Artifact ID**: {artifact_id}
**Collected**: {timestamp}

## Summary
- Text Length: {data.get('text_length', 0)} characters
- URLs Found: {len(data.get('urls', []))}
- IPs Found: {len(data.get('ip_addresses', []))}
- Domains Found: {len(data.get('domains', []))}
- Emails Found: {len(data.get('emails', []))}

## Content Preview
{data.get('text', '')[:1000]}
"""

        return Note(
            id=f"note--{uuid4()}",
            content=content.strip(),
            created=timestamp,
            modified=timestamp,
            created_by_ref=self.author.id,
            labels=["osint", "june-dark"]
        )

    def _create_report(
        self,
        data: Dict[str, Any],
        object_refs: List[str],
        timestamp: str
    ) -> Report:
        """Create STIX report"""

        source_url = data.get('source_url', 'Unknown')

        return Report(
            id=f"report--{uuid4()}",
            created=timestamp,
            modified=timestamp,
            created_by_ref=self.author.id,
            name=f"June Dark OSINT: {source_url[:100]}",
            description=f"OSINT data collected from {source_url}",
            published=timestamp,
            report_types=["threat-report"],
            object_refs=object_refs,
            labels=["osint", "june-dark"],
            external_references=[{
                "source_name": "June Dark OSINT Framework",
                "url": source_url,
                "description": "Original source"
            }],
            confidence=settings.CONNECTOR_CONFIDENCE_LEVEL
        )

    def _map_severity(self, severity: str) -> str:
        """Map June Dark severity to STIX severity"""
        mapping = {
            "critical": "critical",
            "high": "high",
            "medium": "medium",
            "low": "low",
            "info": "low"
        }
        return mapping.get(severity.lower(), "medium")
