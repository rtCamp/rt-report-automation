"""API route registration module."""

from fastapi import Depends, FastAPI

from app.core.auth import validate_api_key
from app.core.config import settings
from app.google_docs.controller import router as google_docs_router
from app.health.controller import router as health_router
from app.llm import llm_router


def register_routes(app: FastAPI):
	"""Register API routes with the FastAPI application.

	Routes are registered with the following authentication scheme:
	- Health check routes: Public (no authentication required)
	- LLM routes: Protected with API key authentication
	- Google Docs routes: Protected with API key authentication

	Authentication is enforced via the validate_api_key dependency which
	requires the X-API-KEY header to be present and valid in all requests
	to protected endpoints.

	Args:
		app (FastAPI): The FastAPI application instance.

	"""
	# Health check endpoint without authentication
	app.include_router(health_router, prefix=settings.API_PREFIX)

	# Protected routes with API key authentication
	app.include_router(
		llm_router,
		prefix=settings.API_PREFIX,
	)
	app.include_router(
		google_docs_router,
		prefix=settings.API_PREFIX,
		dependencies=[Depends(validate_api_key)],
	)
