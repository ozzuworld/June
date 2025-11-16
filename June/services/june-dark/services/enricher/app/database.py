"""
Database manager for Enricher
"""

import logging
from typing import Dict, Any, List
from contextlib import asynccontextmanager

import asyncpg
from neo4j import AsyncGraphDatabase
from elasticsearch import AsyncElasticsearch

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages database connections"""
    
    def __init__(
        self,
        elastic_url: str,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        postgres_dsn: str
    ):
        self.elastic_url = elastic_url
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.postgres_dsn = postgres_dsn
        
        self.pg_pool = None
        self.neo4j_driver = None
        self.es_client = None
    
    async def connect_all(self):
        """Connect to all databases"""
        # PostgreSQL
        try:
            logger.info(f"Connecting to PostgreSQL: {self.postgres_dsn.split('@')[1] if '@' in self.postgres_dsn else self.postgres_dsn}")
            self.pg_pool = await asyncpg.create_pool(
                self.postgres_dsn,
                min_size=5,
                max_size=20
            )
            logger.info("✓ PostgreSQL connected")
        except Exception as e:
            logger.error(f"✗ PostgreSQL connection failed: {e}", exc_info=True)
            raise

        # Neo4j
        try:
            logger.info(f"Connecting to Neo4j: {self.neo4j_uri}")
            self.neo4j_driver = AsyncGraphDatabase.driver(
                self.neo4j_uri,
                auth=(self.neo4j_user, self.neo4j_password)
            )
            logger.info("✓ Neo4j connected")
        except Exception as e:
            logger.error(f"✗ Neo4j connection failed: {e}", exc_info=True)
            raise

        # Elasticsearch
        try:
            logger.info(f"Connecting to Elasticsearch: {self.elastic_url}")
            self.es_client = AsyncElasticsearch([self.elastic_url])
            await self.es_client.ping()
            logger.info("✓ Elasticsearch connected")
        except Exception as e:
            logger.error(f"✗ Elasticsearch connection failed: {e}", exc_info=True)
            raise
    
    async def close_all(self):
        """Close all connections"""
        if self.pg_pool:
            await self.pg_pool.close()
        if self.neo4j_driver:
            await self.neo4j_driver.close()
        if self.es_client:
            await self.es_client.close()
    
    # PostgreSQL methods
    async def pg_fetch(self, query: str, *args) -> List[Dict]:
        """Fetch rows from PostgreSQL"""
        async with self.pg_pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]
    
    async def pg_fetchval(self, query: str, *args):
        """Fetch single value from PostgreSQL"""
        async with self.pg_pool.acquire() as conn:
            return await conn.fetchval(query, *args)
    
    # Neo4j methods
    async def neo4j_write(self, query: str, parameters: Dict = None):
        """Execute Neo4j write query"""
        async with self.neo4j_driver.session() as session:
            await session.run(query, parameters or {})
    
    # Elasticsearch methods
    async def index_document(self, document: Dict[str, Any]):
        """Index document in Elasticsearch"""
        index_name = "june-documents"
        doc_id = document.get("artifact_id")
        
        await self.es_client.index(
            index=index_name,
            id=doc_id,
            document=document
        )
        logger.info(f"Indexed document: {doc_id}")