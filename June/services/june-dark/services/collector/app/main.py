"""
June Dark Collector - Main Worker
Processes crawl requests from RabbitMQ queue
"""

import asyncio
import logging
import json
import signal
import sys
from datetime import datetime
from typing import Dict, Any

import aio_pika
from redis.asyncio import Redis
from minio import Minio

from config import settings
from crawler import WebCrawler
from storage import StorageManager

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CollectorWorker:
    """Main collector worker that processes crawl jobs"""
    
    def __init__(self):
        self.running = False
        self.connection: aio_pika.RobustConnection = None
        self.channel: aio_pika.Channel = None
        self.queue: aio_pika.Queue = None
        self.redis: Redis = None
        self.storage: StorageManager = None
        self.crawler: WebCrawler = None
    
    async def start(self):
        """Initialize and start the worker"""
        logger.info("Starting June Dark Collector Worker...")
        
        try:
            # Connect to Redis
            logger.info("Connecting to Redis...")
            self.redis = Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True
            )
            await self.redis.ping()
            logger.info("✓ Redis connected")
            
            # Initialize MinIO storage
            logger.info("Initializing MinIO storage...")
            self.storage = StorageManager(
                endpoint=settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_SECURE
            )
            logger.info("✓ Storage initialized")
            
            # Initialize crawler
            logger.info("Initializing web crawler...")
            self.crawler = WebCrawler(self.storage, self.redis)
            await self.crawler.initialize()
            logger.info("✓ Crawler initialized")
            
            # Connect to RabbitMQ
            logger.info("Connecting to RabbitMQ...")
            self.connection = await aio_pika.connect_robust(
                settings.RABBIT_URL,
                timeout=30
            )
            self.channel = await self.connection.channel()
            await self.channel.set_qos(prefetch_count=settings.CONCURRENT_REQUESTS)
            
            # Declare queue with TTL and max length
            self.queue = await self.channel.declare_queue(
                "crawl.requests",
                durable=True,
                arguments={
                    "x-message-ttl": 86400000,  # 24 hours in milliseconds
                    "x-max-length": 10000  # Maximum queue length
                }
            )
            logger.info("✓ RabbitMQ connected")
            
            # Start consuming
            self.running = True
            logger.info(f"✓ Collector worker started (mode: {settings.MODE})")
            logger.info(f"  Concurrency: {settings.CONCURRENT_REQUESTS}")
            logger.info(f"  Delay: {settings.DOWNLOAD_DELAY}s")
            
            await self.queue.consume(self.process_message)
            
            # Keep running
            while self.running:
                await asyncio.sleep(1)
        
        except Exception as e:
            logger.error(f"Failed to start worker: {e}")
            raise
    
    async def process_message(self, message: aio_pika.IncomingMessage):
        """Process a single crawl request message"""
        async with message.process():
            try:
                # Parse message
                data = json.loads(message.body.decode())
                logger.info(f"Processing crawl request: {data.get('domain')}")
                
                # Extract job info
                job_id = data.get("job_id")
                target_id = data.get("target_id")
                domain = data.get("domain")
                depth = data.get("depth", 2)
                priority = data.get("priority", 50)
                
                # Update job status to running
                await self.update_job_status(job_id, "running", started_at=True)
                
                # Perform crawl
                result = await self.crawler.crawl_domain(
                    domain=domain,
                    max_depth=depth,
                    job_id=job_id
                )
                
                # Update job with results
                await self.update_job_status(
                    job_id,
                    "completed" if result["success"] else "failed",
                    completed_at=True,
                    pages_crawled=result["pages_crawled"],
                    artifacts_collected=result["artifacts_collected"],
                    error_message=result.get("error")
                )
                
                # Publish result
                await self.publish_result(job_id, result)
                
                logger.info(
                    f"✓ Completed crawl: {domain} "
                    f"({result['pages_crawled']} pages, "
                    f"{result['artifacts_collected']} artifacts)"
                )
            
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                
                # Update job as failed
                job_id = data.get("job_id") if 'data' in locals() else "unknown"
                await self.update_job_status(
                    job_id,
                    "failed",
                    completed_at=True,
                    error_message=str(e)
                )
    
    async def update_job_status(
        self,
        job_id: str,
        status: str,
        started_at: bool = False,
        completed_at: bool = False,
        pages_crawled: int = None,
        artifacts_collected: int = None,
        error_message: str = None
    ):
        """Update job status via Redis"""
        try:
            job_data = {
                "job_id": job_id,
                "status": status,
                "updated_at": datetime.utcnow().isoformat()
            }
            
            if started_at:
                job_data["started_at"] = datetime.utcnow().isoformat()
            
            if completed_at:
                job_data["completed_at"] = datetime.utcnow().isoformat()
            
            if pages_crawled is not None:
                job_data["pages_crawled"] = pages_crawled
            
            if artifacts_collected is not None:
                job_data["artifacts_collected"] = artifacts_collected
            
            if error_message:
                job_data["error_message"] = error_message
            
            # Store in Redis
            await self.redis.setex(
                f"job:{job_id}",
                3600,  # 1 hour TTL
                json.dumps(job_data)
            )
        
        except Exception as e:
            logger.error(f"Failed to update job status: {e}")
    
    async def publish_result(self, job_id: str, result: Dict[str, Any]):
        """Publish crawl result to results queue"""
        try:
            exchange = await self.channel.declare_exchange(
                "june.crawl",
                aio_pika.ExchangeType.TOPIC,
                durable=True
            )
            
            message = aio_pika.Message(
                body=json.dumps({
                    "type": "crawl_result",
                    "job_id": job_id,
                    "result": result,
                    "timestamp": datetime.utcnow().isoformat()
                }).encode(),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT
            )
            
            await exchange.publish(
                message,
                routing_key="crawl.result.completed"
            )
        
        except Exception as e:
            logger.error(f"Failed to publish result: {e}")
    
    async def stop(self):
        """Stop the worker gracefully"""
        logger.info("Stopping collector worker...")
        self.running = False
        
        if self.crawler:
            await self.crawler.close()
        
        if self.connection:
            await self.connection.close()
        
        if self.redis:
            await self.redis.close()
        
        logger.info("✓ Collector worker stopped")


# Signal handlers
worker = None

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}")
    if worker:
        asyncio.create_task(worker.stop())
    sys.exit(0)


async def main():
    """Main entry point"""
    global worker
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start worker
    worker = CollectorWorker()
    await worker.start()


if __name__ == "__main__":
    asyncio.run(main())