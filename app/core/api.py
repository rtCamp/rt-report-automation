from fastapi import FastAPI

from app.core.config import settings
from app.health.controller import router as health_router
from app.llm import llm_router


def register_routes(app: FastAPI):
	app.include_router(health_router, prefix=settings.API_PREFIX)
	app.include_router(llm_router, prefix=settings.API_PREFIX)
