"""Tests for `SlackNotifierService.get_user_email` error handling."""

from unittest.mock import MagicMock

import pytest
from slack_sdk.errors import SlackApiError

from app.slack import notifier as notifier_module
from app.slack.notifier import SlackNotifierService


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> SlackNotifierService:
	monkeypatch.setattr(notifier_module, "redis_client", MagicMock(get=lambda _: None))
	service = SlackNotifierService()
	service.client = MagicMock()
	return service


def api_error(code: str) -> SlackApiError:
	return SlackApiError(message=code, response={"ok": False, "error": code})


def test_unknown_user_returns_none(service):
	service.client.users_info.side_effect = api_error("user_not_found")

	assert service.get_user_email("U0MISSING") is None


def test_other_slack_errors_still_raise(service):
	service.client.users_info.side_effect = api_error("ratelimited")

	# `log_and_raise` can't rebuild a SlackApiError, so it re-raises a plain
	# Exception chained to the original.
	with pytest.raises(Exception, match="looking up user info") as exc:
		service.get_user_email("U0ANY")
	assert isinstance(exc.value.__cause__, SlackApiError)
