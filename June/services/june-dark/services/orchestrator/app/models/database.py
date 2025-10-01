"""
Database manager for multiple database connections with retry logic
"""
import asyncio
import logging
from typing import Optional
import asyncpg
from elasticsearch import AsyncElasticsearch
from neo4j import AsyncGraphDatabase
import redis.asyncio as redis

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, postgres_dsn: str, neo4j_uri: str, neo4j_user: str, 
                 neo4j_password: str, elastic_url: str, redis_url: str):
        self.postgres_dsn = postgres_dsn
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.elastic_url = elastic_url
        self.redis_url = redis_url
        
        self.pg_pool: Optional[asyncpg.Pool] = None
        self.neo4j_driver = None
        self.es_client: Optional[AsyncElasticsearch] = None
        self.redis_client: Optional[redis.Redis] = None
    
    async def connect_with_retry(self, service_name: str, connect_func, max_retries: int = 5):
        """Connect to a service with retry logic"""
        for attempt in range(max_retries):
            try:
                await connect_func()
                logger.info(f"✓ {service_name} connected")
                return True
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"✗ Failed to connect to {service_name} after {max_retries} attempts: {e}")
                    return False
                else:
                    logger.warning(f"Failed to connect to {service_name} (attempt {attempt + 1}/{max_retries}): {e}")
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
        return False
    
    async def connect_all(self):
        """Connect to all databases with resilience"""
        logger.info("Connecting to databases...")
        results = []
        
        # PostgreSQL
        if self.postgres_dsn:
            async def connect_postgres():
                self.pg_pool = await asyncpg.create_pool(
                    self.postgres_dsn, 
                    min_size=1, 
                    max_size=10,
                    command_timeout=5
                )
            
            success = await self.connect_with_retry("PostgreSQL", connect_postgres)
            results.append(("PostgreSQL", success))
        
        # Neo4j
        if self.neo4j_uri:
            async def connect_neo4j():
                self.neo4j_driver = AsyncGraphDatabase.driver(
                    self.neo4j_uri, 
                    auth=(self.neo4j_user, self.neo4j_password)
                )
                # Test the connection
                await self.neo4j_driver.verify_connectivity()
            
            success = await self.connect_with_retry("Neo4j", connect_neo4j)
            results.append(("Neo4j", success))
        
        # Elasticsearch
        if self.elastic_url:
            async def connect_elasticsearch():
                self.es_client = AsyncElasticsearch([self.elastic_url], request_timeout=5)
                await self.es_client.ping()
            
            success = await self.connect_with_retry("Elasticsearch", connect_elasticsearch)
            results.append(("Elasticsearch", success))
        
        # Redis
        if self.redis_url:
            async def connect_redis():
                self.redis_client = redis.from_url(self.redis_url, socket_connect_timeout=5)
                await self.redis_client.ping()
            
            success = await self.connect_with_retry("Redis", connect_redis)
            results.append(("Redis", success))
        
        # Log results
        failed_connections = [name for name, success in results if not success]
        if failed_connections:
            logger.warning(f"Some database connections failed: {', '.join(failed_connections)}")
            logger.info("Orchestrator will continue with available connections")
        else:
            logger.info("All database connections successful!")
    
    async def close_all(self):
        """Close all database connections"""
        logger.info("Closing database connections...")
        
        if self.pg_pool:
            try:
                await self.pg_pool.close()
                logger.info("PostgreSQL connection closed")
            except Exception as e:
                logger.warning(f"Error closing PostgreSQL: {e}")
        
        if self.neo4j_driver:
            try:
                await self.neo4j_driver.close()
                logger.info("Neo4j connection closed")
            except Exception as e:
                logger.warning(f"Error closing Neo4j: {e}")
        
        if self.es_client:
            try:
                await self.es_client.close()
                logger.info("Elasticsearch connection closed")
            except Exception as e:
                logger.warning(f"Error closing Elasticsearch: {e}")
        
        if self.redis_client:
            try:
                await self.redis_client.close()
                logger.info("Redis connection closed")
            except Exception as e:
                logger.warning(f"Error closing Redis: {e}")
