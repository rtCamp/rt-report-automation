"""Shared pytest fixtures.

`app.core.config.settings` is built at import time and requires every secret
to be set, and importing anything under `app.slack` pulls in the Redis
adapter, which pings Redis at import. Dummy settings and a patched ping are
installed here, before any `app` import, so tests need neither a `.env` nor a
running Redis. Real values already in the environment take precedence.
"""

import os
from collections.abc import Callable, Iterator
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

import httpx
import pytest

_TEST_ENV = {
	"APP_API_KEY": "test-api-key",
	"GOOGLE_API_KEY": "test",
	"OPENAI_API_KEY": "test",
	"ANTHROPIC_API_KEY": "test",
	"LANGFUSE_SECRET_KEY": "test",
	"LANGFUSE_PUBLIC_KEY": "test",
	"LANGFUSE_HOST": "https://langfuse.test",
	"INNGEST_DEV": "1",
	"INNGEST_EVENT_KEY": "test",
	"INNGEST_SIGNING_KEY": "test",
	"GITHUB_APP_PRIVATE_KEY": "test",
	"GITHUB_CLIENT_ID": "test",
	"GITHUB_INSTALLATION_ID": "test",
	"REDIS_PASSWORD": "test",
	"SLACK_BOT_TOKEN": "xoxb-test",
	"SLACK_PMS_CONNECTOR_BOT_TOKEN": "xoxb-test",
	"SLACK_PMS_CONNECTOR_SIGNING_SECRET": "test-signing-secret",
	"FRAPPE_BASE_URL": "https://frappe.test",
	"FRAPPE_API_TOKEN": "test:test",
	"GOOGLE_SERVICE_ACCOUNT_KEY": "test",
	"GOOGLE_TEMPLATE_DOC_ID": "test",
}
for _key, _value in _TEST_ENV.items():
	os.environ.setdefault(_key, _value)

with patch("redis.Redis.ping", return_value=True):
	import app.slack  # noqa: F401 -- import once with the ping patched

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.slack import controller  # noqa: E402
from app.slack.auth import verify_slack_signature  # noqa: E402


@pytest.fixture
def slack_command_form() -> Callable[..., str]:
	"""Build the URL-encoded body Slack POSTs for a `/pms` slash command."""

	def build(
		text: str = "",
		*,
		user_id: str = "U0TEST",
		channel_id: str = "C0TEST",
		response_url: str = "https://hooks.slack.com/commands/T0TEST/1/abc",
	) -> str:
		return urlencode(
			{
				"command": "/pms",
				"text": text,
				"user_id": user_id,
				"channel_id": channel_id,
				"response_url": response_url,
			},
		)

	return build


@pytest.fixture
def inngest_send(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
	"""Replace the Inngest client's `send` so no event leaves the test."""
	send = AsyncMock(return_value=["event-id"])
	monkeypatch.setattr(controller.inngest_client, "send", send)
	return send


@pytest.fixture
def slack_client(inngest_send: AsyncMock) -> Iterator[TestClient]:
	"""Serve the Slack router with signature checks switched off.

	Mounts only the Slack router rather than `app.main`, which would also
	register every Inngest function and LLM dependency.
	"""
	app = FastAPI()
	app.include_router(controller.router)
	app.dependency_overrides[verify_slack_signature] = lambda: None
	with TestClient(app) as client:
		yield client


@pytest.fixture
def mock_http(
	monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Callable[[httpx.Request], httpx.Response]], list[httpx.Request]]:
	"""Route every `httpx.AsyncClient` through a handler instead of the network.

	`FrappeService` and `GitHubDataService` build their clients inline, so the
	class is swapped for one with an `httpx.MockTransport` already attached.
	Call the fixture with a handler; it returns the list of requests made.
	"""
	real_async_client = httpx.AsyncClient

	def install(
		handler: Callable[[httpx.Request], httpx.Response],
	) -> list[httpx.Request]:
		requests: list[httpx.Request] = []

		def record(request: httpx.Request) -> httpx.Response:
			requests.append(request)
			return handler(request)

		transport = httpx.MockTransport(record)

		def client_factory(*args, **kwargs) -> httpx.AsyncClient:
			kwargs["transport"] = transport
			return real_async_client(*args, **kwargs)

		monkeypatch.setattr(httpx, "AsyncClient", client_factory)
		return requests

	return install
