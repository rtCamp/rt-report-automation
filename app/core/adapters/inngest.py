import logging
from typing import Any

import inngest
import inngest.fast_api
from fastapi import FastAPI

inngest_client = inngest.Inngest(
	app_id="rt-report-automation",
	logger=logging.getLogger("uvicorn"),
)


def setup_inngest(app: FastAPI, functions: list[Any] = []):
	"""Setup Inngest with the FastAPI application.

	Args:
		app (FastAPI): The FastAPI application instance.

	Returns:
		None
	"""
	inngest.fast_api.serve(app, inngest_client, functions)
