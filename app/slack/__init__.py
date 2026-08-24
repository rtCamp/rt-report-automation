"""Initialization of the slack module."""

from app.slack.controller import audit_router
from app.slack.controller import router as slack_router
from app.slack.service import SlackService

__all__ = ["SlackService", "audit_router", "slack_router"]
