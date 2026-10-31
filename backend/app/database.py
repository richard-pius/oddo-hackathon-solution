"""
Async SQLAlchemy engine & session factory.

Why async everywhere:
  Billing Day can touch thousands of rows. Async lets us overlap DB I/O with
  JSON serialization so the event loop stays responsive for SSE heartbeats
  and portal users who happen to be browsing during the batch run.
"""

from typing import Any, AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

is_sqlite = "sqlite" in settings.DATABASE_URL
engine_kwargs: dict[str, Any] = {"echo": False}
if not is_sqlite:
    engine_kwargs.update({
        "pool_size": 20,
        "max_overflow": 10,
        "pool_pre_ping": True,
    })

engine = create_async_engine(
    settings.DATABASE_URL,
    **engine_kwargs
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a session that auto-closes after the request."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
