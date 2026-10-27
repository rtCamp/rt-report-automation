"""Initialization of the slack module."""

from app.slack.controller import allocation_router, audit_router
from app.slack.controller import router as slack_router
from app.slack.service import SlackService

__all__ = ["SlackService", "allocation_router", "audit_router", "slack_router"]
