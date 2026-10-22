"""Resolve `/pms timesheets` targets and decide what the requester may see.

Runs before any timesheet is fetched. Delivery Managers see everything; a PM
sees only entries on projects they manage. The Sales Manager override that
`/pms audit` honours deliberately does not apply here.
"""

import asyncio
import re

from app.frappe.constants import DELIVERY_MANAGER_ROLE
from app.frappe.service import FrappeService
from app.slack.constants import SLACK_EMAIL_UNREADABLE_TEXT
from app.slack.models.timesheets import (
	AccessScope,
	ResolvedEmployee,
	ResolvedTargets,
	TimesheetQuery,
)
from app.slack.notifier import SlackNotifierService

# `<@U123ABC>` or `<@U123ABC|name>`, as Slack sends a mention in command text.
_SLACK_MENTION = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")


class TimesheetAccessError(ValueError):
	"""The request can't proceed; the message is written for the Slack user."""


async def resolve_timesheet_targets(
	query: TimesheetQuery,
	slack_user_id: str,
	frappe: FrappeService,
	notifier: SlackNotifierService,
) -> ResolvedTargets:
	"""Resolve the query's targets and the requester's access scope.

	Args:
		query (TimesheetQuery): The parsed request.
		slack_user_id (str): The requester's Slack user ID.
		frappe (FrappeService): Service for Frappe lookups.
		notifier (SlackNotifierService): Service for Slack email lookups.

	Returns:
		ResolvedTargets: What to fetch and the scope to filter it by.
			Unknown or inaccessible targets are listed, and the rest proceed.

	Raises:
		TimesheetAccessError: If the requester's email can't be read, or no
			target is left once unknown and inaccessible ones are dropped.

	"""
	requester_email = await asyncio.to_thread(notifier.get_user_email, slack_user_id)
	if not requester_email:
		raise TimesheetAccessError(SLACK_EMAIL_UNREADABLE_TEXT)

	roles = await frappe.get_user_roles(requester_email)
	is_delivery_manager = DELIVERY_MANAGER_ROLE in roles
	managed_ids: set[str] = set()
	if not is_delivery_manager:
		managed = await frappe.get_projects_by_manager_email(requester_email)
		managed_ids = {project["name"] for project in managed}

	if query.target_type == "projects":
		return await _resolve_projects(
			query.targets,
			frappe,
			is_delivery_manager=is_delivery_manager,
			managed_ids=managed_ids,
		)
	return await _resolve_members(
		query.targets,
		frappe,
		notifier,
		is_delivery_manager=is_delivery_manager,
		managed_ids=managed_ids,
	)


async def _resolve_projects(
	targets: list[str],
	frappe: FrappeService,
	*,
	is_delivery_manager: bool,
	managed_ids: set[str],
) -> ResolvedTargets:
	"""Resolve project IDs, checking each against the requester's access."""
	not_found: list[str] = []
	denied: list[str] = []
	allowed: list[str] = []

	if is_delivery_manager:
		projects = await asyncio.gather(*(frappe.get_project_by_id(t) for t in targets))
		for target, project in zip(targets, projects, strict=True):
			(allowed if project else not_found).append(target)
	else:
		# A PM's own list is the only thing they can see, so an unknown ID and
		# one they don't manage are the same answer: no existence leak.
		for target in targets:
			(allowed if target in managed_ids else denied).append(target)

	if not allowed:
		raise TimesheetAccessError(_nothing_left_text("project", not_found, denied))

	scope = AccessScope(
		all_projects=is_delivery_manager,
		project_ids=[] if is_delivery_manager else allowed,
	)
	return ResolvedTargets(
		scope=scope,
		project_ids=allowed,
		not_found=not_found,
		denied=denied,
	)


async def _resolve_members(
	targets: list[str],
	frappe: FrappeService,
	notifier: SlackNotifierService,
	*,
	is_delivery_manager: bool,
	managed_ids: set[str],
) -> ResolvedTargets:
	"""Resolve Employee IDs, emails and Slack mentions, checking allocation."""
	identifiers = await _mentions_to_emails(targets, notifier)
	records = await frappe.get_employees([i for i in identifiers.values() if i])

	by_key: dict[str, ResolvedEmployee] = {}
	for record in records:
		employee = ResolvedEmployee(
			employee_id=record["name"],
			employee_name=record.get("employee_name") or record["name"],
			email=record.get("user_id") or record.get("company_email"),
		)
		for key in (record["name"], record.get("user_id"), record.get("company_email")):
			if key:
				by_key[key.lower()] = employee

	employees: list[ResolvedEmployee] = []
	not_found: list[str] = []
	for target, identifier in identifiers.items():
		employee = by_key.get(identifier.lower()) if identifier else None
		if employee is None:
			not_found.append(target)
		elif employee not in employees:
			employees.append(employee)

	denied: list[str] = []
	scope = AccessScope(all_projects=True)
	if not is_delivery_manager and employees:
		emails = [e.email for e in employees if e.email]
		shared = await frappe.get_shared_project_ids(emails, sorted(managed_ids))
		allowed: list[ResolvedEmployee] = []
		scope_ids: set[str] = set()
		for employee in employees:
			projects = shared.get(employee.email or "", set())
			if projects:
				allowed.append(employee)
				scope_ids |= projects
			else:
				denied.append(employee.employee_id)
		employees = allowed
		scope = AccessScope(all_projects=False, project_ids=sorted(scope_ids))

	if not employees:
		raise TimesheetAccessError(_nothing_left_text("member", not_found, denied))

	return ResolvedTargets(
		scope=scope, employees=employees, not_found=not_found, denied=denied
	)


async def _mentions_to_emails(
	targets: list[str], notifier: SlackNotifierService
) -> dict[str, str | None]:
	"""Map each target to a lookup key, turning Slack mentions into emails.

	A mention whose profile has no email maps to `None`, so it is reported as
	not found rather than silently dropped.
	"""
	resolved: dict[str, str | None] = {}
	for target in targets:
		match = _SLACK_MENTION.fullmatch(target)
		if match:
			resolved[target] = await asyncio.to_thread(
				notifier.get_user_email, match.group(1)
			)
		else:
			resolved[target] = target
	return resolved


def _nothing_left_text(kind: str, not_found: list[str], denied: list[str]) -> str:
	"""Build the error shown when no target survives resolution."""
	lines = []
	if not_found:
		lines.append(f"No {kind} found for {_ticks(not_found)}.")
	if denied:
		lines.append(f"You don't have access to review {_ticks(denied)}.")
	return "⚠️ " + " ".join(lines)


def _ticks(items: list[str]) -> str:
	return ", ".join(f"`{item}`" for item in items)
