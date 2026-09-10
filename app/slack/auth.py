"""Slack request signature verification."""

import hashlib
import hmac
import time
from urllib.parse import urlsplit

from fastapi import Header, Request

from app.core.config import settings
from app.core.exceptions import AuthenticationError

_MAX_REQUEST_AGE_SECONDS = 60 * 5

# `response_url` arrives inside a signed request but is still caller-supplied
# data, so its host is validated before any outbound POST (CodeQL: SSRF).
_SLACK_RESPONSE_URL_HOST = "hooks.slack.com"


def is_slack_response_url(url: str) -> bool:
	"""Whether a Slack `response_url` is safe to POST to.

	Parses the URL rather than prefix-matching it: `https://hooks.slack.com/`
	as a plain string prefix also matches `hooks.slack.com.evil.com`.
	"""
	try:
		parts = urlsplit(url)
	except ValueError:
		return False
	return parts.scheme == "https" and parts.hostname == _SLACK_RESPONSE_URL_HOST


async def verify_slack_signature(
	request: Request,
	x_slack_signature: str = Header(...),
	x_slack_request_timestamp: str = Header(...),
) -> None:
	"""Verify that a request genuinely came from Slack.

	Follows Slack's request signing spec: the signature is an HMAC-SHA256 of
	``v0:{timestamp}:{raw body}`` keyed with the app's signing secret.

	Args:
		request (Request): The incoming FastAPI request.
		x_slack_signature (str): The ``X-Slack-Signature`` header.
		x_slack_request_timestamp (str): The ``X-Slack-Request-Timestamp`` header.

	Raises:
		AuthenticationError: If the timestamp is stale or the signature does
			not match.

	"""
	try:
		request_timestamp = int(x_slack_request_timestamp)
	except ValueError as exc:
		raise AuthenticationError(message="Invalid Slack request timestamp") from exc

	if abs(time.time() - request_timestamp) > _MAX_REQUEST_AGE_SECONDS:
		raise AuthenticationError(message="Slack request timestamp too old")

	body = await request.body()
	base_string = f"v0:{x_slack_request_timestamp}:{body.decode()}"
	computed_signature = (
		"v0="
		+ hmac.new(
			settings.SLACK_PMS_CONNECTOR_SIGNING_SECRET.get_secret_value().encode(),
			base_string.encode(),
			hashlib.sha256,
		).hexdigest()
	)

	if not hmac.compare_digest(computed_signature, x_slack_signature):
		raise AuthenticationError(message="Invalid Slack signature")
