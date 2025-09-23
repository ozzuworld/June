from typing import AsyncIterator
import os

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # Example default for local dev; override in prod
    DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/june_db"

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    session = SessionLocal()
    try:
        yield session
    finally:
        await session.close()
