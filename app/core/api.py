from fastapi import FastAPI

from app.health.controller import router as health_router
from app.llm import llm_router


def register_routes(app: FastAPI):
	app.include_router(health_router)
	app.include_router(llm_router)
