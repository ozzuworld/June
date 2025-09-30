"""
RabbitMQ Queue Manager
"""

import asyncio
import logging
import json
from typing import Dict, Any, Optional, Callable
from datetime import datetime
import aio_pika
from aio_pika import Message, ExchangeType

logger = logging.getLogger(__name__)


class QueueManager:
    """Manages RabbitMQ connections and message publishing"""
    
    def __init__(self, rabbit_url: str):
        self.rabbit_url = rabbit_url
        self.connection: Optional[aio_pika.RobustConnection] = None
        self.channel: Optional[aio_pika.Channel] = None
        self.exchanges: Dict[str, aio_pika.Exchange] = {}
        self.queues: Dict[str, aio_pika.Queue] = {}
        self.connected = False
    
    async def connect(self):
        """Establish connection to RabbitMQ"""
        try:
            logger.info("Connecting to RabbitMQ...")
            
            self.connection = await aio_pika.connect_robust(
                self.rabbit_url,
                timeout=30
            )
            
            self.channel = await self.connection.channel()
            await self.channel.set_qos(prefetch_count=10)
            
            # Declare exchanges
            await self._declare_exchanges()
            
            # Declare queues
            await self._declare_queues()
            
            self.connected = True
            logger.info("✓ RabbitMQ connected successfully")
            
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise
    
    async def _declare_exchanges(self):
        """Declare all required exchanges"""
        exchange_configs = [
            ("june.crawl", ExchangeType.TOPIC),
            ("june.enrichment", ExchangeType.TOPIC),
            ("june.vision", ExchangeType.TOPIC),
            ("june.alerts", ExchangeType.FANOUT),
        ]
        
        for name, exchange_type in exchange_configs:
            exchange = await self.channel.declare_exchange(
                name,
                exchange_type,
                durable=True
            )
            self.exchanges[name] = exchange
            logger.info(f"✓ Exchange declared: {name}")
    
    async def _declare_queues(self):
        """Declare all required queues"""
        queue_configs = [
            ("crawl.requests", {"x-max-length": 10000, "x-message-ttl": 86400000}),
            ("crawl.results", {"x-max-length": 10000, "x-message-ttl": 86400000}),
            ("enrichment.requests", {"x-max-length": 50000, "x-message-ttl": 86400000}),
            ("enrichment.results", {"x-max-length": 50000, "x-message-ttl": 86400000}),
            ("vision.requests", {"x-max-length": 20000, "x-message-ttl": 86400000}),
            ("vision.results", {"x-max-length": 20000, "x-message-ttl": 86400000}),
            ("alerts.queue", {"x-max-length": 5000, "x-message-ttl": 604800000}),
            ("dead_letter", {}),
        ]
        
        for name, arguments in queue_configs:
            queue = await self.channel.declare_queue(
                name,
                durable=True,
                arguments=arguments
            )
            self.queues[name] = queue
            logger.info(f"✓ Queue declared: {name}")
    
    async def publish(
        self,
        exchange_name: str,
        routing_key: str,
        message: Dict[str, Any],
        priority: int = 0
    ):
        """Publish message to exchange"""
        if not self.connected:
            raise RuntimeError("Not connected to RabbitMQ")
        
        exchange = self.exchanges.get(exchange_name)
        if not exchange:
            raise ValueError(f"Exchange not found: {exchange_name}")
        
        # Add metadata
        message["_metadata"] = {
            "timestamp": datetime.utcnow().isoformat(),
            "source": "orchestrator",
            "routing_key": routing_key
        }
        
        # Create message
        msg = Message(
            body=json.dumps(message).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            priority=priority
        )
        
        # Publish
        await exchange.publish(msg, routing_key=routing_key)
        logger.debug(f"Published message to {exchange_name}/{routing_key}")
    
    async def publish_crawl_request(self, target: Dict[str, Any]):
        """Publish crawl request"""
        await self.publish(
            "june.crawl",
            "crawl.request.scheduled",
            {
                "type": "crawl_request",
                "target": target
            }
        )
    
    async def publish_enrichment_request(self, artifact: Dict[str, Any]):
        """Publish enrichment request"""
        await self.publish(
            "june.enrichment",
            "enrich.request.artifact",
            {
                "type": "enrichment_request",
                "artifact": artifact
            }
        )
    
    async def publish_vision_request(self, image_data: Dict[str, Any]):
        """Publish vision analysis request"""
        await self.publish(
            "june.vision",
            "vision.request.image",
            {
                "type": "vision_request",
                "image": image_data
            }
        )
    
    async def publish_alert(self, alert: Dict[str, Any]):
        """Publish alert"""
        await self.publish(
            "june.alerts",
            "",  # Fanout exchange doesn't use routing key
            {
                "type": "alert",
                "alert": alert
            },
            priority=9  # High priority
        )
    
    async def get_queue_stats(self, queue_name: str) -> Dict[str, Any]:
        """Get queue statistics"""
        if queue_name not in self.queues:
            raise ValueError(f"Queue not found: {queue_name}")
        
        queue = self.queues[queue_name]
        
        # This triggers a passive declaration that returns queue info
        result = await self.channel.declare_queue(
            queue_name,
            passive=True
        )
        
        return {
            "name": queue_name,
            "messages": result.declaration_result.message_count,
            "consumers": result.declaration_result.consumer_count
        }
    
    async def get_all_queue_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all queues"""
        stats = {}
        for queue_name in self.queues.keys():
            try:
                stats[queue_name] = await self.get_queue_stats(queue_name)
            except Exception as e:
                logger.error(f"Failed to get stats for {queue_name}: {e}")
                stats[queue_name] = {"error": str(e)}
        return stats
    
    async def purge_queue(self, queue_name: str):
        """Purge all messages from a queue"""
        if queue_name not in self.queues:
            raise ValueError(f"Queue not found: {queue_name}")
        
        queue = self.queues[queue_name]
        await queue.purge()
        logger.info(f"Purged queue: {queue_name}")
    
    async def close(self):
        """Close RabbitMQ connection"""
        if self.connection:
            await self.connection.close()
            self.connected = False
            logger.info("✓ RabbitMQ connection closed")