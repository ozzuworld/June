"""
Database connection manager for multiple data stores
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

import asyncpg
from neo4j import AsyncGraphDatabase
from elasticsearch import AsyncElasticsearch
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages connections to PostgreSQL, Neo4j, Elasticsearch, and Redis"""
    
    def __init__(
        self,
        postgres_dsn: str,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        elastic_url: str,
        redis_url: str
    ):
        self.postgres_dsn = postgres_dsn
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.elastic_url = elastic_url
        self.redis_url = redis_url
        
        # Connection objects
        self.pg_pool: Optional[asyncpg.Pool] = None
        self.neo4j_driver = None
        self.es_client: Optional[AsyncElasticsearch] = None
        self.redis_client: Optional[Redis] = None
        
        self.connected = False
    
    async def connect_all(self):
        """Connect to all databases"""
        try:
            # PostgreSQL
            logger.info("Connecting to PostgreSQL...")
            self.pg_pool = await asyncpg.create_pool(
                self.postgres_dsn,
                min_size=5,
                max_size=20,
                command_timeout=60
            )
            logger.info("✓ PostgreSQL connected")
            
            # Neo4j
            logger.info("Connecting to Neo4j...")
            self.neo4j_driver = AsyncGraphDatabase.driver(
                self.neo4j_uri,
                auth=(self.neo4j_user, self.neo4j_password),
                max_connection_pool_size=50
            )
            # Test connection
            async with self.neo4j_driver.session() as session:
                await session.run("RETURN 1")
            logger.info("✓ Neo4j connected")
            
            # Elasticsearch
            logger.info("Connecting to Elasticsearch...")
            self.es_client = AsyncElasticsearch([self.elastic_url])
            # Test connection
            await self.es_client.ping()
            logger.info("✓ Elasticsearch connected")
            
            # Redis
            logger.info("Connecting to Redis...")
            self.redis_client = Redis.from_url(
                self.redis_url,
                decode_responses=True,
                max_connections=10
            )
            # Test connection
            await self.redis_client.ping()
            logger.info("✓ Redis connected")
            
            self.connected = True
            logger.info("✓ All databases connected successfully")
            
        except Exception as e:
            logger.error(f"Failed to connect to databases: {e}")
            await self.close_all()
            raise
    
    async def close_all(self):
        """Close all database connections"""
        logger.info("Closing database connections...")
        
        if self.pg_pool:
            await self.pg_pool.close()
            logger.info("✓ PostgreSQL closed")
        
        if self.neo4j_driver:
            await self.neo4j_driver.close()
            logger.info("✓ Neo4j closed")
        
        if self.es_client:
            await self.es_client.close()
            logger.info("✓ Elasticsearch closed")
        
        if self.redis_client:
            await self.redis_client.close()
            logger.info("✓ Redis closed")
        
        self.connected = False
    
    # PostgreSQL operations
    @asynccontextmanager
    async def pg_connection(self):
        """Get PostgreSQL connection from pool"""
        async with self.pg_pool.acquire() as conn:
            yield conn
    
    async def pg_execute(self, query: str, *args):
        """Execute PostgreSQL query"""
        async with self.pg_connection() as conn:
            return await conn.execute(query, *args)
    
    async def pg_fetch(self, query: str, *args) -> List[Dict]:
        """Fetch rows from PostgreSQL"""
        async with self.pg_connection() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]
    
    async def pg_fetchrow(self, query: str, *args) -> Optional[Dict]:
        """Fetch single row from PostgreSQL"""
        async with self.pg_connection() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None
    
    async def pg_fetchval(self, query: str, *args):
        """Fetch single value from PostgreSQL"""
        async with self.pg_connection() as conn:
            return await conn.fetchval(query, *args)
    
    # Neo4j operations
    @asynccontextmanager
    async def neo4j_session(self):
        """Get Neo4j session"""
        async with self.neo4j_driver.session() as session:
            yield session
    
    async def neo4j_run(self, query: str, parameters: Dict = None) -> List[Dict]:
        """Run Neo4j query and return results"""
        async with self.neo4j_session() as session:
            result = await session.run(query, parameters or {})
            return [dict(record) async for record in result]
    
    async def neo4j_write(self, query: str, parameters: Dict = None):
        """Run Neo4j write query"""
        async with self.neo4j_session() as session:
            await session.run(query, parameters or {})
    
    # Elasticsearch operations
    async def es_index(self, index: str, document: Dict, doc_id: str = None):
        """Index document in Elasticsearch"""
        return await self.es_client.index(
            index=index,
            document=document,
            id=doc_id
        )
    
    async def es_search(self, index: str, query: Dict) -> Dict:
        """Search Elasticsearch"""
        return await self.es_client.search(index=index, body=query)
    
    async def es_get(self, index: str, doc_id: str) -> Dict:
        """Get document by ID from Elasticsearch"""
        return await self.es_client.get(index=index, id=doc_id)
    
    async def es_delete(self, index: str, doc_id: str):
        """Delete document from Elasticsearch"""
        return await self.es_client.delete(index=index, id=doc_id)
    
    async def es_bulk(self, operations: List[Dict]):
        """Bulk operations in Elasticsearch"""
        from elasticsearch.helpers import async_bulk
        return await async_bulk(self.es_client, operations)
    
    # Redis operations
    async def redis_get(self, key: str) -> Optional[str]:
        """Get value from Redis"""
        return await self.redis_client.get(key)
    
    async def redis_set(self, key: str, value: str, ex: int = None):
        """Set value in Redis"""
        return await self.redis_client.set(key, value, ex=ex)
    
    async def redis_delete(self, key: str):
        """Delete key from Redis"""
        return await self.redis_client.delete(key)
    
    async def redis_exists(self, key: str) -> bool:
        """Check if key exists in Redis"""
        return await self.redis_client.exists(key) > 0
    
    async def redis_incr(self, key: str) -> int:
        """Increment counter in Redis"""
        return await self.redis_client.incr(key)
    
    async def redis_expire(self, key: str, seconds: int):
        """Set expiration on key"""
        return await self.redis_client.expire(key, seconds)
    
    # Health checks
    async def health_check(self) -> Dict[str, Any]:
        """Check health of all database connections"""
        health = {
            "postgres": False,
            "neo4j": False,
            "elasticsearch": False,
            "redis": False
        }
        
        try:
            # PostgreSQL
            if self.pg_pool:
                async with self.pg_connection() as conn:
                    await conn.fetchval("SELECT 1")
                health["postgres"] = True
        except Exception as e:
            logger.error(f"PostgreSQL health check failed: {e}")
        
        try:
            # Neo4j
            if self.neo4j_driver:
                async with self.neo4j_session() as session:
                    await session.run("RETURN 1")
                health["neo4j"] = True
        except Exception as e:
            logger.error(f"Neo4j health check failed: {e}")
        
        try:
            # Elasticsearch
            if self.es_client:
                await self.es_client.ping()
                health["elasticsearch"] = True
        except Exception as e:
            logger.error(f"Elasticsearch health check failed: {e}")
        
        try:
            # Redis
            if self.redis_client:
                await self.redis_client.ping()
                health["redis"] = True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
        
        return health