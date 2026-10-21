"""Tests for resolving `/pms timesheets` targets and enforcing access."""

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.slack.constants import SLACK_EMAIL_UNREADABLE_TEXT
from app.slack.models.timesheets import TimesheetQuery
from app.slack.services.timesheet_access import (
	TimesheetAccessError,
	resolve_timesheet_targets,
)

ALICE = {
	"name": "EMP-001",
	"employee_name": "Alice",
	"user_id": "alice@rt.com",
	"company_email": "alice@rt.com",
}
BOB = {
	"name": "EMP-002",
	"employee_name": "Bob",
	"user_id": "bob@rt.com",
	"company_email": "bob@rt.com",
}
EMPLOYEES = [ALICE, BOB]


def make_query(target_type, targets):
	return TimesheetQuery(
		action="fetch",
		target_type=target_type,
		targets=targets,
		from_date=dt.date(2026, 9, 21),
		to_date=dt.date(2026, 9, 25),
		checks=[],
	)


def make_frappe(
	*, roles=(), managed=(), shares=None, projects=("PROJ-1", "PROJ-2", "PROJ-3")
):
	"""Build a FrappeService stand-in backed by in-memory data."""
	frappe = MagicMock()
	frappe.get_user_roles = AsyncMock(return_value=list(roles))
	frappe.get_projects_by_manager_email = AsyncMock(
		return_value=[{"name": p} for p in managed],
	)

	async def get_employees(identifiers):
		wanted = {i.lower() for i in identifiers}
		return [
			e for e in EMPLOYEES if wanted & {e["name"].lower(), e["user_id"].lower()}
		]

	frappe.get_employees = AsyncMock(side_effect=get_employees)
	frappe.get_project_by_id = AsyncMock(
		side_effect=lambda pid: {"name": pid} if pid in projects else None,
	)
	shares = shares or {}
	frappe.get_shared_project_ids = AsyncMock(
		side_effect=lambda emails, ids: {
			e: set(shares[e]) & set(ids)
			for e in emails
			if set(shares.get(e, ())) & set(ids)
		},
	)
	return frappe


def make_notifier(emails=None):
	"""Build a notifier mapping Slack user IDs to emails; the requester is U0REQ."""
	emails = {"U0REQ": "pm@rt.com", **(emails or {})}
	notifier = MagicMock()
	notifier.get_user_email = MagicMock(side_effect=emails.get)
	return notifier


async def resolve(query, frappe, notifier=None):
	return await resolve_timesheet_targets(
		query, "U0REQ", frappe, notifier or make_notifier()
	)


# Resolution


async def test_id_email_and_mention_resolve_to_the_same_employee():
	notifier = make_notifier({"U0ALICE": "alice@rt.com"})
	frappe = make_frappe(roles=["Delivery Manager"])

	for target in ("EMP-001", "alice@rt.com", "<@U0ALICE>", "<@U0ALICE|alice>"):
		result = await resolve(make_query("members", [target]), frappe, notifier)
		assert [e.employee_id for e in result.employees] == ["EMP-001"]


async def test_unknown_ids_are_reported_and_known_ones_continue():
	frappe = make_frappe(roles=["Delivery Manager"])

	result = await resolve(make_query("members", ["EMP-001", "EMP-999"]), frappe)

	assert [e.employee_id for e in result.employees] == ["EMP-001"]
	assert result.not_found == ["EMP-999"]


async def test_all_unknown_is_an_error():
	frappe = make_frappe(roles=["Delivery Manager"])

	with pytest.raises(TimesheetAccessError, match="EMP-999"):
		await resolve(make_query("members", ["EMP-999"]), frappe)


async def test_mention_without_email_is_not_found():
	notifier = make_notifier()
	frappe = make_frappe(roles=["Delivery Manager"])

	result = await resolve(
		make_query("members", ["EMP-001", "<@U0NOMAIL>"]), frappe, notifier
	)

	assert result.not_found == ["<@U0NOMAIL>"]


async def test_requester_without_email_gets_the_profile_warning():
	notifier = MagicMock()
	notifier.get_user_email = MagicMock(return_value=None)
	frappe = make_frappe()

	with pytest.raises(TimesheetAccessError) as exc:
		await resolve(make_query("projects", ["PROJ-1"]), frappe, notifier)

	assert str(exc.value) == SLACK_EMAIL_UNREADABLE_TEXT
	frappe.get_user_roles.assert_not_awaited()


# Projects


async def test_pm_can_review_own_project():
	frappe = make_frappe(managed=["PROJ-1"])

	result = await resolve(make_query("projects", ["PROJ-1"]), frappe)

	assert result.project_ids == ["PROJ-1"]
	assert not result.scope.all_projects
	assert result.scope.project_ids == ["PROJ-1"]


async def test_pm_is_denied_a_project_they_do_not_manage():
	frappe = make_frappe(managed=["PROJ-1"])

	with pytest.raises(TimesheetAccessError, match="PROJ-2"):
		await resolve(make_query("projects", ["PROJ-2"]), frappe)

	# Nothing past the access check was queried.
	frappe.get_project_by_id.assert_not_awaited()


async def test_pm_mixed_projects_keep_the_managed_ones():
	frappe = make_frappe(managed=["PROJ-1"])

	result = await resolve(make_query("projects", ["PROJ-1", "PROJ-2"]), frappe)

	assert result.project_ids == ["PROJ-1"]
	assert result.denied == ["PROJ-2"]


async def test_delivery_manager_reviews_any_project_with_scope_all():
	frappe = make_frappe(roles=["Delivery Manager"])

	result = await resolve(make_query("projects", ["PROJ-3", "PROJ-X"]), frappe)

	assert result.scope.all_projects
	assert result.project_ids == ["PROJ-3"]
	assert result.not_found == ["PROJ-X"]
	frappe.get_projects_by_manager_email.assert_not_awaited()


async def test_sales_manager_who_is_not_the_pm_is_denied():
	frappe = make_frappe(roles=["Sales Manager"], managed=[])

	with pytest.raises(TimesheetAccessError, match="PROJ-1"):
		await resolve(make_query("projects", ["PROJ-1"]), frappe)


# Members


async def test_pm_member_scope_is_limited_to_the_pms_projects():
	# Alice is on PROJ-1 (managed) and PROJ-3 (not managed).
	frappe = make_frappe(
		managed=["PROJ-1", "PROJ-2"],
		shares={"alice@rt.com": ["PROJ-1", "PROJ-3"]},
	)

	result = await resolve(make_query("members", ["EMP-001"]), frappe)

	assert not result.scope.all_projects
	assert result.scope.project_ids == ["PROJ-1"]


async def test_pm_is_denied_a_member_not_on_any_of_their_projects():
	frappe = make_frappe(managed=["PROJ-1"], shares={"alice@rt.com": ["PROJ-3"]})

	with pytest.raises(TimesheetAccessError, match="EMP-001"):
		await resolve(make_query("members", ["EMP-001"]), frappe)


async def test_pm_mixed_members_keep_the_allocated_ones():
	frappe = make_frappe(managed=["PROJ-1"], shares={"alice@rt.com": ["PROJ-1"]})

	result = await resolve(make_query("members", ["EMP-001", "EMP-002"]), frappe)

	assert [e.employee_id for e in result.employees] == ["EMP-001"]
	assert result.denied == ["EMP-002"]


async def test_delivery_manager_reviews_any_member_with_scope_all():
	frappe = make_frappe(roles=["Delivery Manager"])

	result = await resolve(make_query("members", ["EMP-001", "EMP-002"]), frappe)

	assert result.scope.all_projects
	assert len(result.employees) == 2
	frappe.get_shared_project_ids.assert_not_awaited()


async def test_unknown_mention_does_not_abort_valid_targets():
	# A mention Slack can't find maps to no email (see the notifier), and the
	# valid employee alongside it still resolves.
	notifier = make_notifier({"U0MISSING": None})
	frappe = make_frappe(roles=["Delivery Manager"])

	result = await resolve(
		make_query("members", ["EMP-001", "<@U0MISSING>"]), frappe, notifier
	)

	assert [e.employee_id for e in result.employees] == ["EMP-001"]
	assert result.not_found == ["<@U0MISSING>"]
