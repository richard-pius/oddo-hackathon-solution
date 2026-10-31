"""
Brightloop Software Subscription Management System
====================================================
FastAPI application entry point. Assembles all routers, configures CORS,
and sets up the APScheduler for nightly billing batch runs.

Why we initialize the scheduler in the lifespan context:
  APScheduler's AsyncIOScheduler must share the same event loop as FastAPI.
  Using the lifespan hook guarantees the scheduler starts after uvicorn's
  loop is running and shuts down cleanly on SIGTERM without orphan threads.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.database import engine, Base
from app.routers import auth, catalog, subscriptions, billing, payments, analytics, stream

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("brightloop")

# APScheduler for nightly billing
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: create tables (dev convenience) and start the billing scheduler.
    Shutdown: gracefully stop the scheduler so in-flight billing batches
    can finish their current chunk before the process exits.
    """
    # Create tables if they don't exist (Alembic handles migrations in prod)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Schedule the nightly billing run
    from app.services.billing_engine import run_billing_batch
    scheduler.add_job(
        run_billing_batch,
        "cron",
        hour=settings.BILLING_CRON_HOUR,
        minute=settings.BILLING_CRON_MINUTE,
        id="nightly_billing",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"🚀 Brightloop started. Billing cron: {settings.BILLING_CRON_HOUR}:{settings.BILLING_CRON_MINUTE:02d}")

    yield

    scheduler.shutdown(wait=True)
    await engine.dispose()
    logger.info("🛑 Brightloop shutdown complete")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Enterprise Subscription & Recurring Billing Platform",
    lifespan=lifespan,
)

# CORS — allow the Astro frontend and dev tools
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Seamless alias: Rewrite /api/... to /api/v1/... so both paths work flawlessly
@app.middleware("http")
async def api_version_fallback(request, call_next):
    path = request.url.path
    if path.startswith("/api/") and not path.startswith("/api/v1/") and path != "/api/health":
        request.scope["path"] = "/api/v1" + path[4:]
    return await call_next(request)

# Mount all routers — each is a self-contained domain module
app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(subscriptions.router)
app.include_router(billing.router)
app.include_router(payments.router)
app.include_router(analytics.router)
app.include_router(stream.router)


@app.get("/api/health")
async def health_check():
    """Load balancer health probe. Returns 200 if the app is alive."""
    return {"status": "healthy", "version": settings.APP_VERSION}
