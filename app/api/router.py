"""Central API router assembling all sub-routers."""

from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.policies import router as policies_router
from app.api.repositories import router as repositories_router
from app.api.reviews import router as reviews_router
from app.api.webhooks import router as webhooks_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health_router)
api_router.include_router(webhooks_router)
api_router.include_router(reviews_router)
api_router.include_router(repositories_router)
api_router.include_router(policies_router)
