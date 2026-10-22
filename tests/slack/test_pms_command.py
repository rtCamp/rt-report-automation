"""Tests for the `/pms` slash command endpoint."""

from app.slack.constants import PMS_USAGE_TEXT, TIMESHEET_USAGE_TEXT

ENDPOINT = "/slack/commands"
FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}


def post_command(client, form, text):
	return client.post(ENDPOINT, content=form(text), headers=FORM_HEADERS)


# /pms timesheets


def test_bare_timesheets_shows_usage(slack_client, slack_command_form, inngest_send):
	response = post_command(slack_client, slack_command_form, "timesheets")

	assert response.json() == {
		"response_type": "ephemeral",
		"text": TIMESHEET_USAGE_TEXT,
	}
	inngest_send.assert_not_awaited()


def test_valid_timesheets_command_is_echoed_back(
	slack_client,
	slack_command_form,
	inngest_send,
):
	response = post_command(
		slack_client,
		slack_command_form,
		"timesheets analyze --members EMP-001,EMP-002 "
		"--from 2026-09-21 --to 2026-09-25 --checks duplicates,gaps",
	)

	body = response.json()
	assert body["response_type"] == "ephemeral"
	assert "*analyze* 2 members (`EMP-001`, `EMP-002`)" in body["text"]
	assert "21 Sep 2026 – 25 Sep 2026 (5 days)" in body["text"]
	assert "Checks: duplicates, gaps." in body["text"]
	inngest_send.assert_not_awaited()


def test_invalid_timesheets_command_shows_error_only(slack_client, slack_command_form):
	response = post_command(
		slack_client,
		slack_command_form,
		"timesheets fetch --projects PROJ-1 --from 2026-02-30 --to 2026-03-02",
	)

	body = response.json()
	assert body["response_type"] == "ephemeral"
	assert "not a valid date" in body["text"]
	assert TIMESHEET_USAGE_TEXT not in body["text"]


def test_unknown_flag_shows_error_and_usage(slack_client, slack_command_form):
	response = post_command(
		slack_client,
		slack_command_form,
		"timesheets fetch --projects P --from 2026-09-01 --to 2026-09-02 --verbose",
	)

	text = response.json()["text"]
	assert "Unknown flag `--verbose`" in text
	assert text.endswith(TIMESHEET_USAGE_TEXT)


# Existing subcommands keep their behaviour.


def test_unknown_subcommand_shows_usage(slack_client, slack_command_form, inngest_send):
	response = post_command(slack_client, slack_command_form, "bogus")

	assert response.json() == {"response_type": "in_channel", "text": PMS_USAGE_TEXT}
	inngest_send.assert_not_awaited()


def test_projects_is_queued_silently(slack_client, slack_command_form, inngest_send):
	response = post_command(slack_client, slack_command_form, "projects")

	assert response.status_code == 200
	assert response.content == b""
	event = inngest_send.await_args.args[0]
	assert event.name == "rt-report-automation/pms_command"
	assert event.data["subcommand"] == "projects"
	assert event.data["project_filter"] is None


def test_missing_fields_passes_filter(slack_client, slack_command_form, inngest_send):
	response = post_command(
		slack_client, slack_command_form, "missing-fields PROJ-0669"
	)

	assert response.content == b""
	event = inngest_send.await_args.args[0]
	assert event.data["subcommand"] == "missing-fields"
	assert event.data["project_filter"] == "PROJ-0669"


def test_bare_audit_opens_picker(slack_client, slack_command_form, inngest_send):
	response = post_command(slack_client, slack_command_form, "audit")

	body = response.json()
	assert body["response_type"] == "in_channel"
	assert body["text"] == "Which project would you like to audit?"
	assert body["blocks"]
	inngest_send.assert_not_awaited()


def test_audit_with_id_is_queued_with_pending_message(
	slack_client,
	slack_command_form,
	inngest_send,
):
	response = post_command(slack_client, slack_command_form, "AUDIT PROJ-0669")

	body = response.json()
	assert body["response_type"] == "in_channel"
	assert "PROJ-0669" in body["text"]
	event = inngest_send.await_args.args[0]
	assert event.data["subcommand"] == "audit"
	assert event.data["project_filter"] == "PROJ-0669"


def test_queue_failure_reports_error(slack_client, slack_command_form, inngest_send):
	inngest_send.side_effect = RuntimeError("inngest down")

	response = post_command(slack_client, slack_command_form, "projects")

	assert "Something went wrong" in response.json()["text"]
