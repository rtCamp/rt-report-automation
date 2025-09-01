from fastapi import FastAPI

from app.health.controller import router as health_router


def register_routes(app: FastAPI):
	app.include_router(health_router)
