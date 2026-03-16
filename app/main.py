"""DiffMaster FastAPI application entry point."""

import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.router import api_router
from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "diffmaster_starting",
        version=__version__,
        env=settings.app_env,
    )
    yield
    logger.info("diffmaster_shutting_down")


app = FastAPI(
    title="DiffMaster",
    description="Intelligent Automated Code Review API",
    version=__version__,
    docs_url="/docs" if settings.app_debug else None,
    redoc_url="/redoc" if settings.app_debug else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000

    if not request.url.path.startswith(("/health", "/ready", "/docs", "/redoc", "/openapi")):
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration_ms, 2),
        )

    response.headers["X-Request-Duration-Ms"] = str(round(duration_ms, 2))
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled_exception", path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


app.include_router(api_router)


@app.get("/")
async def root():
    return {
        "service": "DiffMaster",
        "version": __version__,
        "description": "Intelligent Automated Code Review API",
        "docs": "/docs" if settings.app_debug else None,
    }
