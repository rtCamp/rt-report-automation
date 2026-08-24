"""Inngest adapter module."""

import logging
from typing import Any

import inngest
import inngest.fast_api
from fastapi import FastAPI

inngest_client = inngest.Inngest(
	app_id="rt-report-automation",
	logger=logging.getLogger("uvicorn"),
)


def setup_inngest(app: FastAPI, functions: list[Any] | None = None):
	"""Set up Inngest with FastAPI.

	Args:
		app (FastAPI): The FastAPI application instance.
		functions (list[Any], optional): List of Inngest functions. Defaults to [].


	"""
	inngest.fast_api.serve(app, inngest_client, functions or [])
