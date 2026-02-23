"""Inngest proxy module for forwarding status requests to the Inngest API."""

from app.inngest_proxy.controller import router as inngest_proxy_router

__all__ = ["inngest_proxy_router"]
