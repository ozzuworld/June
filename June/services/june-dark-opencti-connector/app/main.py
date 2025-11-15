"""
June Dark OpenCTI Connector - Main Worker
Bridges June Dark OSINT Framework with OpenCTI
"""

import asyncio
import json
import logging
import signal
import sys
from datetime import datetime
from typing import Dict, Any

import aio_pika
from fastapi import FastAPI
from pycti import OpenCTIConnectorHelper, get_config_variable
import uvicorn

from .config import settings
from .stix_converter import STIXConverter

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.CONNECTOR_LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# FastAPI for health checks
app = FastAPI(title="June Dark OpenCTI Connector", version=settings.CONNECTOR_VERSION)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "connector": settings.CONNECTOR_NAME,
        "version": settings.CONNECTOR_VERSION,
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    global connector_worker
    if connector_worker:
        return {
            "messages_processed": connector_worker.messages_processed,
            "messages_failed": connector_worker.messages_failed,
            "bundles_sent": connector_worker.bundles_sent,
            "uptime_seconds": (datetime.utcnow() - connector_worker.start_time).total_seconds()
        }
    return {"status": "not_started"}


class JuneDarkConnector:
    """June Dark to OpenCTI connector worker"""

    def __init__(self):
        self.running = False
        self.connection: aio_pika.RobustConnection = None
        self.channel: aio_pika.Channel = None
        self.queue: aio_pika.Queue = None
        self.helper: OpenCTIConnectorHelper = None
        self.stix_converter: STIXConverter = None

        # Metrics
        self.messages_processed = 0
        self.messages_failed = 0
        self.bundles_sent = 0
        self.start_time = datetime.utcnow()

    async def start(self):
        """Initialize and start the connector"""
        logger.info(f"Starting {settings.CONNECTOR_NAME} v{settings.CONNECTOR_VERSION}")

        try:
            # Initialize OpenCTI connector helper
            logger.info("Connecting to OpenCTI...")
            config = {
                "opencti": {
                    "url": settings.OPENCTI_URL,
                    "token": settings.OPENCTI_TOKEN,
                    "ssl_verify": settings.OPENCTI_SSL_VERIFY
                },
                "connector": {
                    "id": settings.CONNECTOR_ID,
                    "name": settings.CONNECTOR_NAME,
                    "scope": settings.CONNECTOR_SCOPE,
                    "confidence_level": settings.CONNECTOR_CONFIDENCE_LEVEL,
                    "log_level": settings.CONNECTOR_LOG_LEVEL,
                    "version": settings.CONNECTOR_VERSION
                }
            }

            self.helper = OpenCTIConnectorHelper(config)
            logger.info("✓ Connected to OpenCTI")

            # Initialize STIX converter
            self.stix_converter = STIXConverter(self.helper)
            logger.info("✓ STIX converter initialized")

            # Connect to June Dark RabbitMQ
            logger.info("Connecting to June Dark RabbitMQ...")
            self.connection = await aio_pika.connect_robust(
                settings.RABBITMQ_URL,
                timeout=30
            )
            self.channel = await self.connection.channel()
            await self.channel.set_qos(prefetch_count=settings.PREFETCH_COUNT)

            # Declare exchange and queue
            exchange = await self.channel.declare_exchange(
                settings.RABBITMQ_EXCHANGE,
                aio_pika.ExchangeType.TOPIC,
                durable=True
            )

            self.queue = await self.channel.declare_queue(
                settings.RABBITMQ_QUEUE,
                durable=True
            )

            # Bind queue to exchange for enrichment results
            await self.queue.bind(exchange, routing_key="enrichment.#")
            logger.info("✓ Connected to June Dark RabbitMQ")

            # Start consuming
            self.running = True
            logger.info(f"✓ {settings.CONNECTOR_NAME} started successfully")
            logger.info(f"Listening for messages on queue: {settings.RABBITMQ_QUEUE}")

            await self.queue.consume(self.process_message)

            # Keep running
            while self.running:
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Failed to start connector: {e}", exc_info=True)
            raise

    async def process_message(self, message: aio_pika.IncomingMessage):
        """Process enrichment message from June Dark"""

        async with message.process():
            try:
                # Parse message
                data = json.loads(message.body.decode())
                logger.info(f"Received message: {data.get('artifact_id', 'unknown')}")

                # Determine message type
                message_type = data.get("type", "enriched_data")

                if message_type == "enriched_data":
                    await self._process_enriched_data(data)
                elif message_type == "alert":
                    await self._process_alert(data)
                else:
                    logger.warning(f"Unknown message type: {message_type}")
                    return

                self.messages_processed += 1
                logger.info(f"✓ Processed message (total: {self.messages_processed})")

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse message JSON: {e}")
                self.messages_failed += 1
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                self.messages_failed += 1

    async def _process_enriched_data(self, data: Dict[str, Any]):
        """Process enriched data and send to OpenCTI"""

        try:
            artifact_id = data.get("artifact_id", "unknown")
            logger.info(f"Converting enriched data to STIX: {artifact_id}")

            # Convert to STIX bundle
            bundle = self.stix_converter.convert_enriched_data(data)

            # Send to OpenCTI
            logger.info(f"Sending {len(bundle.objects)} STIX objects to OpenCTI")
            self.helper.send_stix2_bundle(bundle.serialize())

            self.bundles_sent += 1
            logger.info(f"✓ Sent bundle to OpenCTI (artifact: {artifact_id})")

        except Exception as e:
            logger.error(f"Failed to process enriched data: {e}", exc_info=True)
            raise

    async def _process_alert(self, alert: Dict[str, Any]):
        """Process alert and send to OpenCTI as incident"""

        try:
            alert_id = alert.get("id", "unknown")
            logger.info(f"Converting alert to STIX incident: {alert_id}")

            # Convert to STIX bundle
            bundle = self.stix_converter.convert_alert(alert)

            # Send to OpenCTI
            logger.info(f"Sending alert as incident to OpenCTI")
            self.helper.send_stix2_bundle(bundle.serialize())

            self.bundles_sent += 1
            logger.info(f"✓ Sent alert to OpenCTI (alert: {alert_id})")

        except Exception as e:
            logger.error(f"Failed to process alert: {e}", exc_info=True)
            raise

    async def stop(self):
        """Stop the connector gracefully"""
        logger.info("Stopping connector...")
        self.running = False

        if self.connection:
            await self.connection.close()

        logger.info("✓ Connector stopped")


# Global connector instance
connector_worker = None


def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}")
    if connector_worker:
        asyncio.create_task(connector_worker.stop())
    sys.exit(0)


async def start_connector():
    """Start the connector worker"""
    global connector_worker

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    connector_worker = JuneDarkConnector()
    await connector_worker.start()


async def main():
    """Main entry point - run both API and connector"""

    # Start connector in background
    connector_task = asyncio.create_task(start_connector())

    # Start FastAPI server for health checks
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8000,
        log_level=settings.CONNECTOR_LOG_LEVEL.lower()
    )
    server = uvicorn.Server(config)

    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
