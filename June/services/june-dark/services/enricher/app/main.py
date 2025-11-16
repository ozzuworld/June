"""
June Dark Enricher - Main Worker
Processes enrichment requests and indexes data
"""

import asyncio
import logging
import json
import signal
import sys
from datetime import datetime
from typing import Dict, Any

import aio_pika
from fastapi import FastAPI
import uvicorn

from config import settings
from processors import TextProcessor, MetadataProcessor, AlertProcessor
from database import DatabaseManager
from storage import StorageManager

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# FastAPI app for health checks
app = FastAPI(title="June Dark Enricher", version="1.0.0")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "enricher",
        "timestamp": datetime.utcnow().isoformat()
    }


class EnricherWorker:
    """Main enricher worker"""
    
    def __init__(self):
        self.running = False
        self.connection: aio_pika.RobustConnection = None
        self.channel: aio_pika.Channel = None
        self.queue: aio_pika.Queue = None
        self.db: DatabaseManager = None
        self.storage: StorageManager = None
        self.text_processor: TextProcessor = None
        self.metadata_processor: MetadataProcessor = None
        self.alert_processor: AlertProcessor = None
    
    async def start(self):
        """Initialize and start the worker"""
        logger.info("Starting June Dark Enricher Worker...")
        
        try:
            # Initialize database connections
            logger.info("Connecting to databases...")
            self.db = DatabaseManager(
                elastic_url=settings.ELASTIC_URL,
                neo4j_uri=settings.NEO4J_URI,
                neo4j_user=settings.NEO4J_USER,
                neo4j_password=settings.NEO4J_PASSWORD,
                postgres_dsn=settings.POSTGRES_DSN
            )
            await self.db.connect_all()
            logger.info("✓ Databases connected")
            
            # Initialize storage
            logger.info("Initializing storage...")
            self.storage = StorageManager(
                endpoint=settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_SECURE
            )
            logger.info("✓ Storage initialized")
            
            # Initialize processors
            logger.info("Initializing processors...")
            self.text_processor = TextProcessor(self.db, self.storage)
            self.metadata_processor = MetadataProcessor(self.db)
            self.alert_processor = AlertProcessor(self.db)
            logger.info("✓ Processors initialized")
            
            # Connect to RabbitMQ
            logger.info("Connecting to RabbitMQ...")
            self.connection = await aio_pika.connect_robust(
                settings.RABBIT_URL,
                timeout=30
            )
            self.channel = await self.connection.channel()
            await self.channel.set_qos(prefetch_count=settings.BATCH_SIZE)
            
            # Declare queue with TTL and max length
            self.queue = await self.channel.declare_queue(
                "enrichment.requests",
                durable=True,
                arguments={
                    "x-message-ttl": 86400000,  # 24 hours in milliseconds
                    "x-max-length": 10000  # Maximum queue length
                }
            )
            logger.info("✓ RabbitMQ connected")
            
            # Start consuming
            self.running = True
            logger.info("✓ Enricher worker started")
            
            await self.queue.consume(self.process_message)
            
            # Keep running
            while self.running:
                await asyncio.sleep(1)
        
        except Exception as e:
            logger.error(f"Failed to start worker: {e}")
            raise
    
    async def process_message(self, message: aio_pika.IncomingMessage):
        """Process a single enrichment request"""
        async with message.process():
            try:
                # Parse message
                data = json.loads(message.body.decode())
                artifact = data.get("artifact", {})
                
                logger.info(f"Processing artifact: {artifact.get('id')}")
                
                # Process based on artifact type
                artifact_type = artifact.get("artifact_type")
                
                if artifact_type in ["html", "text"]:
                    await self._process_text_artifact(artifact)
                elif artifact_type in ["image", "screenshot"]:
                    await self._process_image_artifact(artifact)
                elif artifact_type == "pdf":
                    await self._process_pdf_artifact(artifact)
                else:
                    logger.warning(f"Unknown artifact type: {artifact_type}")
                
                logger.info(f"✓ Processed artifact: {artifact.get('id')}")
            
            except Exception as e:
                logger.error(f"Error processing message: {e}")
    
    async def _process_text_artifact(self, artifact: Dict[str, Any]):
        """Process text/HTML artifacts"""
        try:
            # Download from MinIO
            artifact_data = self.storage.download_data(
                settings.BUCKET_ARTIFACTS,
                artifact["minio_path"]
            )
            
            # Extract and process text
            result = await self.text_processor.process(
                text=artifact_data.decode('utf-8', errors='ignore'),
                artifact_id=artifact["id"],
                source_url=artifact["source_url"]
            )
            
            # Check for alerts
            alerts = await self.alert_processor.check_text(
                text=result["text"],
                artifact_id=artifact["id"],
                source_url=artifact["source_url"]
            )
            
            if alerts:
                await self._publish_alerts(alerts)
            
            # Index in Elasticsearch
            await self.db.index_document(result)
            
            # Create graph relationships
            await self._create_graph_relationships(result)
        
        except Exception as e:
            logger.error(f"Error processing text artifact: {e}")
    
    async def _process_image_artifact(self, artifact: Dict[str, Any]):
        """Process image artifacts (queue for vision worker)"""
        try:
            # Create vision request
            vision_request = {
                "artifact_id": artifact["id"],
                "minio_path": artifact["minio_path"],
                "source_url": artifact["source_url"],
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Publish to vision queue
            exchange = await self.channel.declare_exchange(
                "june.vision",
                aio_pika.ExchangeType.TOPIC,
                durable=True
            )
            
            message = aio_pika.Message(
                body=json.dumps(vision_request).encode(),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT
            )
            
            await exchange.publish(message, routing_key="vision.request.image")
            logger.info(f"Queued image for vision analysis: {artifact['id']}")
        
        except Exception as e:
            logger.error(f"Error processing image artifact: {e}")
    
    async def _process_pdf_artifact(self, artifact: Dict[str, Any]):
        """Process PDF artifacts"""
        try:
            # Download PDF
            pdf_data = self.storage.download_data(
                settings.BUCKET_ARTIFACTS,
                artifact["minio_path"]
            )
            
            # Extract text from PDF
            import pdfplumber
            from io import BytesIO
            
            text_parts = []
            with pdfplumber.open(BytesIO(pdf_data)) as pdf:
                for page in pdf.pages:
                    text_parts.append(page.extract_text())
            
            full_text = "\n\n".join(text_parts)
            
            # Process as text
            result = await self.text_processor.process(
                text=full_text,
                artifact_id=artifact["id"],
                source_url=artifact["source_url"]
            )
            
            # Check for alerts
            alerts = await self.alert_processor.check_text(
                text=full_text,
                artifact_id=artifact["id"],
                source_url=artifact["source_url"]
            )
            
            if alerts:
                await self._publish_alerts(alerts)
            
            # Index in Elasticsearch
            await self.db.index_document(result)
        
        except Exception as e:
            logger.error(f"Error processing PDF artifact: {e}")
    
    async def _create_graph_relationships(self, result: Dict[str, Any]):
        """Create Neo4j graph relationships"""
        try:
            # Extract entities (simplified - in production use NER)
            urls = result.get("urls", [])
            emails = result.get("emails", [])
            domains = result.get("domains", [])
            
            # Create document node
            doc_id = result["artifact_id"]
            await self.db.neo4j_write(
                """
                MERGE (d:Document {id: $doc_id})
                SET d.url = $url,
                    d.timestamp = datetime($timestamp)
                """,
                {
                    "doc_id": doc_id,
                    "url": result["source_url"],
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            
            # Create domain relationships
            for domain in domains:
                await self.db.neo4j_write(
                    """
                    MERGE (dom:Domain {name: $domain})
                    MERGE (d:Document {id: $doc_id})
                    MERGE (d)-[:MENTIONS]->(dom)
                    """,
                    {"domain": domain, "doc_id": doc_id}
                )
            
            # Create email relationships
            for email in emails:
                await self.db.neo4j_write(
                    """
                    MERGE (e:Email {address: $email})
                    MERGE (d:Document {id: $doc_id})
                    MERGE (d)-[:CONTAINS]->(e)
                    """,
                    {"email": email, "doc_id": doc_id}
                )
        
        except Exception as e:
            logger.error(f"Error creating graph relationships: {e}")
    
    async def _publish_alerts(self, alerts: list):
        """Publish alerts to alert queue"""
        try:
            exchange = await self.channel.declare_exchange(
                "june.alerts",
                aio_pika.ExchangeType.FANOUT,
                durable=True
            )
            
            for alert in alerts:
                message = aio_pika.Message(
                    body=json.dumps(alert).encode(),
                    content_type="application/json",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    priority=9
                )
                
                await exchange.publish(message, routing_key="")
                logger.info(f"Published alert: {alert['alert_type']}")
        
        except Exception as e:
            logger.error(f"Error publishing alerts: {e}")
    
    async def stop(self):
        """Stop the worker gracefully"""
        logger.info("Stopping enricher worker...")
        self.running = False
        
        if self.connection:
            await self.connection.close()
        
        if self.db:
            await self.db.close_all()
        
        logger.info("✓ Enricher worker stopped")


# Global worker instance
worker = None


def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}")
    if worker:
        asyncio.create_task(worker.stop())
    sys.exit(0)


async def start_worker():
    """Start the worker"""
    global worker
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    worker = EnricherWorker()
    await worker.start()


async def main():
    """Main entry point - run both API and worker"""
    # Start worker in background
    worker_task = asyncio.create_task(start_worker())
    
    # Start FastAPI server
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=9010,
        log_level=settings.LOG_LEVEL.lower()
    )
    server = uvicorn.Server(config)
    
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())