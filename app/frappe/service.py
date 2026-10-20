"""Service for interacting with the Frappe PMS REST API."""

import datetime as dt
import json
import logging
import re
from typing import cast

import httpx

from app.core.adapters.redis import redis_client
from app.core.config import settings
from app.core.utils import log_and_raise
from app.frappe.constants import (
	COMMENT_DOCTYPE,
	DOCSHARE_DOCTYPE,
	GITHUB_REPOSITORY_DOCTYPE,
	HAS_ROLE_DOCTYPE,
	NON_BILLABLE_TYPE,
	PROJECT_BILLING_TYPE_FIELD,
	PROJECT_DETAIL_FIELDS,
	PROJECT_DOCTYPE,
	PROJECT_MANAGER_FIELD,
	PROJECT_SUPPRESSED_STATUSES,
	PROJECT_TIMELINE_ITEM_DOCTYPE,
	RESOURCE_ALLOCATION_CONFIRMED_STATUS,
	RESOURCE_ALLOCATION_DOCTYPE,
	RISK_DOCTYPE,
	TODO_DOCTYPE,
	USER_DOCTYPE,
	USER_ROLES_CACHE_KEY,
	USER_ROLES_CACHE_TTL,
)


class FrappeValidationError(Exception):
	"""Frappe rejected a write (4xx), carrying its user-facing message."""


def _frappe_error_message(response: httpx.Response) -> str:
	"""Extract the human-readable message from a Frappe error response."""
	try:
		body = response.json()
	except ValueError:
		text = re.sub(r"<[^>]+>", " ", response.text)
		return " ".join(text.split())[:300] or f"HTTP {response.status_code}"

	messages = []
	try:
		for raw in json.loads(body.get("_server_messages") or "[]"):
			message = json.loads(raw).get("message") if raw.startswith("{") else raw
			if message:
				messages.append(str(message))
	except (TypeError, ValueError, AttributeError):
		pass

	fallback = body.get("exception") or body.get("exc_type") or ""
	text = " ".join(messages) or str(fallback)
	return re.sub(r"<[^>]+>", "", text).strip() or f"HTTP {response.status_code}"


class FrappeService:
	"""Service for reading Project records from Frappe PMS."""

	def __init__(self):
		"""Initialize the FrappeService."""
		self.base_url = str(settings.FRAPPE_BASE_URL).rstrip("/")
		self.headers = {
			"Authorization": f"token {settings.FRAPPE_API_TOKEN.get_secret_value()}",
		}
		self.logger = logging.getLogger(__name__)

	async def get_projects_by_manager_email(self, email: str) -> list[dict]:
		"""Fetch projects whose manager matches the given email.

		Args:
			email (str): The project manager's email address.

		Returns:
			list[dict]: Matching project records, each containing `name`,
				`project_name`, `status`, and every fieldname in
				``PROJECT_DETAIL_FIELDS``. Empty only if none match --
				a non-2xx response raises instead of returning `[]`, so a
				Frappe outage isn't indistinguishable from "no projects".

		"""
		fields = ["name", "project_name", "status"] + [
			fieldname for fieldname, _ in PROJECT_DETAIL_FIELDS
		]
		params = {
			"filters": json.dumps([[PROJECT_MANAGER_FIELD, "=", email]]),
			"fields": json.dumps(fields),
			"limit_page_length": 0,
		}

		try:
			async with httpx.AsyncClient() as client:
				response = await client.get(
					f"{self.base_url}/api/resource/{PROJECT_DOCTYPE}",
					headers=self.headers,
					params=params,
				)

			response.raise_for_status()
			return response.json().get("data", [])

		except Exception as exc:
			log_and_raise(
				self.logger,
				"Exception occurred while fetching projects from Frappe",
				exception_type=exc.__class__,
				cause=exc,
			)

	async def get_billable_open_projects(self) -> list[dict]:
		"""Fetch every active, billable project, for the scheduler-triggered bulk audit.

		"Active" excludes `PROJECT_SUPPRESSED_STATUSES` (On hold, Completed,
		Cancelled) rather than requiring status == "Open", so any other
		in-progress status value still gets audited.

		Unlike `get_projects_by_manager_email`, this isn't scoped to a known
		manager -- it fetches `PROJECT_MANAGER_FIELD` (the PM's email)
		directly in the results so the caller can route each project's
		audit to the right person.

		Returns:
			list[dict]: Project records with `name`, `project_name`,
				`status`, the PM's email, and every fieldname in
				``PROJECT_DETAIL_FIELDS``. Empty if none match or the
				lookup fails.

		"""
		fields = ["name", "project_name", "status", PROJECT_MANAGER_FIELD] + [
			fieldname for fieldname, _ in PROJECT_DETAIL_FIELDS
		]
		filters = [
			["status", "not in", list(PROJECT_SUPPRESSED_STATUSES)],
			[PROJECT_BILLING_TYPE_FIELD, "!=", NON_BILLABLE_TYPE],
		]
		return await self._fetch_list(PROJECT_DOCTYPE, filters, fields)

	async def search_projects(self, query: str, limit: int = 25) -> list[dict]:
		"""Search active projects by name or ID, across every project.

		Backs the `/pms audit` project picker, which needs to search the whole
		project list rather than the requester's own -- a CSM reviewing someone
		else's project has no bounded "my projects" set to filter within.

		Suppressed-status projects are excluded so the picker doesn't offer
		completed or cancelled work, matching `get_billable_open_projects`.

		Args:
			query (str): Free text matched against project name and ID. An
				empty query returns the first `limit` active projects, which
				is what Slack sends when the menu is first opened.
			limit (int): Maximum results. Slack renders at most 100 options.

		Returns:
			list[dict]: Records with `name`, `project_name` and `status`.

		"""
		filters: list[list] = [
			["status", "not in", list(PROJECT_SUPPRESSED_STATUSES)],
		]

		# `or_filters` so typing either the ID or the name finds the project.
		or_filters = (
			[
				["name", "like", f"%{query}%"],
				["project_name", "like", f"%{query}%"],
			]
			if query
			else []
		)

		params = {
			"filters": json.dumps(filters),
			"fields": json.dumps(["name", "project_name", "status"]),
			"limit_page_length": limit,
			"order_by": "modified desc",
		}
		if or_filters:
			params["or_filters"] = json.dumps(or_filters)

		try:
			async with httpx.AsyncClient() as client:
				response = await client.get(
					f"{self.base_url}/api/resource/{PROJECT_DOCTYPE}",
					headers=self.headers,
					params=params,
				)

			response.raise_for_status()
			return response.json().get("data", [])

		except Exception as exc:
			log_and_raise(
				self.logger,
				"Exception occurred while searching projects in Frappe",
				exception_type=exc.__class__,
				cause=exc,
			)

	async def _fetch_list(
		self,
		doctype: str,
		filters: list,
		fields: list[str],
	) -> list[dict]:
		"""Fetch a filtered, field-limited list of records for a doctype.

		Args:
			doctype (str): The Frappe doctype to query (e.g. "Task").
			filters (list): Frappe list-view style filters, e.g.
				``[["project", "=", "PROJ-0001"]]``.
			fields (list[str]): Fieldnames to return for each record.

		Returns:
			list[dict]: Matching records. Empty only if none match -- a
				non-2xx response raises instead of returning `[]`, so a
				Frappe outage isn't indistinguishable from "no records".

		"""
		params = {
			"filters": json.dumps(filters),
			"fields": json.dumps(fields),
			"limit_page_length": 0,
		}

		try:
			async with httpx.AsyncClient() as client:
				response = await client.get(
					f"{self.base_url}/api/resource/{doctype}",
					headers=self.headers,
					params=params,
				)

			response.raise_for_status()
			return response.json().get("data", [])

		except Exception as exc:
			log_and_raise(
				self.logger,
				f"Exception occurred while fetching {doctype} from Frappe",
				exception_type=exc.__class__,
				cause=exc,
			)

	async def get_project_by_id(self, project_id: str) -> dict | None:
		"""Fetch a single project document by its ID, including child tables.

		Unlike the list endpoint, a single-document fetch returns child
		table data (e.g. GitHub repository connections), which is needed
		for the /pms audit command.

		Args:
			project_id (str): The Frappe Project `name` (e.g. "PROJ-0669").

		Returns:
			dict | None: The full project document, or None if it doesn't
				exist or the lookup fails.

		"""
		try:
			async with httpx.AsyncClient() as client:
				response = await client.get(
					f"{self.base_url}/api/resource/{PROJECT_DOCTYPE}/{project_id}",
					headers=self.headers,
				)

			# Only a 404 means "no such project". Anything else (403, 5xx) is a
			# permission problem or an outage, and must not be reported to the
			# user as a bad project ID.
			if response.status_code == httpx.codes.NOT_FOUND:
				self.logger.info("Project %s not found in Frappe", project_id)
				return None

			response.raise_for_status()
			return response.json().get("data")

		except Exception as exc:
			log_and_raise(
				self.logger,
				"Exception occurred while fetching project from Frappe",
				exception_type=exc.__class__,
				cause=exc,
			)

	async def get_user_roles(self, email: str) -> list[str]:
		"""Fetch the Frappe roles assigned to a user.

		Reads the `Has Role` child table directly rather than the `roles` key
		on the parent User document: a site granting read on `User` but not on
		`Has Role` returns that key silently emptied, which is indistinguishable
		from "no roles" and quietly denies the audit override.

		Powers the /pms audit command's privileged-role override (see
		`PROJECT_AUDIT_OVERRIDE_ROLES`).

		Args:
			email (str): The user's email (Frappe User `name`).

		Returns:
			list[str]: Role names, e.g. ["Employee", "Delivery Manager"].
				Empty only when the user genuinely has no roles.

		Raises:
			Exception: If the lookup fails. Deliberately not degraded to `[]`:
				that would read as "not privileged" and tell an eligible CSM
				to request a role they already hold.

		"""
		cache_key = USER_ROLES_CACHE_KEY.format(email=email)
		try:
			cached = redis_client.get(cache_key)
			if cached is not None:
				return json.loads(cast("str", cached))
		except Exception as exc:
			# A cache miss must never break the lookup -- fall through to
			# Frappe and just pay the round-trip.
			self.logger.warning("Could not read cached roles for %s: %s", email, exc)

		params = {
			"filters": json.dumps([["parent", "=", email]]),
			"fields": json.dumps(["role"]),
			"limit_page_length": 0,
			# Required by Frappe for child-table reads -- it identifies which
			# parent doctype the rows belong to. Omitting it returns a 403.
			"parent": USER_DOCTYPE,
		}

		try:
			async with httpx.AsyncClient() as client:
				response = await client.get(
					f"{self.base_url}/api/resource/{HAS_ROLE_DOCTYPE}",
					headers=self.headers,
					params=params,
				)

			response.raise_for_status()

			rows = response.json().get("data") or []
			roles = [row["role"] for row in rows if row.get("role")]

			try:
				redis_client.set(
					cache_key,
					json.dumps(roles),
					ex=USER_ROLES_CACHE_TTL,
				)
			except Exception as exc:
				self.logger.warning(
					"Could not cache roles for %s: %s",
					email,
					exc,
				)

			return roles

		except Exception as exc:
			log_and_raise(
				self.logger,
				"Exception occurred while fetching user roles from Frappe",
				exception_type=exc.__class__,
				cause=exc,
			)

	async def get_milestones_by_project(self, project_id: str) -> list[dict]:
		"""Fetch Project Timeline Item records (type=Milestone) for a project.

		This is the primary milestone source powering the ?tab=calendar view
		in Next PMS. Returns records from the `Project Timeline Item` doctype
		(module "Next Projects") filtered to type="Milestone".

		Args:
			project_id (str): The Frappe Project `name` (e.g. "PROJ-0669").

		Returns:
			list[dict]: Milestone records with `name`, `title`,
				`item_owner_name`, `is_complete`, `start_date`,
				`planned_end_date`, and `actual_end_date`.

		"""
		return await self._fetch_list(
			PROJECT_TIMELINE_ITEM_DOCTYPE,
			[["project", "=", project_id], ["type", "=", "Milestone"]],
			[
				"name",
				"title",
				"item_owner_name",
				"is_complete",
				"start_date",
				"planned_end_date",
				"actual_end_date",
			],
		)

	async def get_todos_by_project(self, project_id: str) -> list[dict]:
		"""Fetch standalone ToDo records (Frappe's generic to-do list) for a project.

		The sole source for the /pms audit's todos section -- `Task` records
		are no longer queried for todos.

		Args:
			project_id (str): The Frappe Project `name`.

		Returns:
			list[dict]: ToDo records with `name`, `custom_title`,
				`description`, `status`, and `date` (the due date, may be
				None).

		"""
		return await self._fetch_list(
			TODO_DOCTYPE,
			[
				["reference_type", "=", PROJECT_DOCTYPE],
				["reference_name", "=", project_id],
			],
			["name", "custom_title", "description", "status", "date"],
		)

	async def get_risks_by_project(self, project_id: str) -> list[dict]:
		"""Fetch all Risk records for a project.

		Args:
			project_id (str): The Frappe Project `name`.

		Returns:
			list[dict]: Risk records with `name`, `status`, `risk_level`,
				`risk_category`, and `summary`.

		"""
		return await self._fetch_list(
			RISK_DOCTYPE,
			[["project", "=", project_id]],
			["name", "status", "risk_level", "risk_category", "summary"],
		)

	async def get_project_shares(self, project_id: str) -> list[str]:
		"""Fetch the emails of every user this Project record is shared with.

		Next PMS has no dedicated "team members" field -- the Members
		panel's team list is derived from Frappe's document sharing
		(`DocShare`), so this is what backs the /pms audit's team-roster
		check (see `DOCSHARE_DOCTYPE`'s docstring in constants.py).

		Args:
			project_id (str): The Frappe Project `name`.

		Returns:
			list[str]: User emails the project is shared with. Empty if
				none or the lookup fails.

		"""
		shares = await self._fetch_list(
			DOCSHARE_DOCTYPE,
			[["share_doctype", "=", PROJECT_DOCTYPE], ["share_name", "=", project_id]],
			["user"],
		)
		return [share["user"] for share in shares if share.get("user")]

	async def get_github_repositories(self, names: list[str]) -> list[dict]:
		"""Fetch display info for a set of GitHub Repository records.

		Args:
			names (list[str]): GitHub Repository document names.

		Returns:
			list[dict]: Records with `name`, `repository_owner`, and
				`repository_name`. Empty if `names` is empty.

		"""
		if not names:
			return []

		return await self._fetch_list(
			GITHUB_REPOSITORY_DOCTYPE,
			[["name", "in", names]],
			["name", "repository_owner", "repository_name"],
		)

	async def get_allocations_ending_on(self, end_date: dt.date) -> list[dict]:
		"""Fetch confirmed allocations with a project whose last day is `end_date`.

		Args:
			end_date (dt.date): The allocation end date to match.

		Returns:
			list[dict]: Records with `name`, `employee`, `employee_name`,
				`project`, `project_name`, `allocation_end_date`,
				`hours_allocated_per_day` and `modified`.

		"""
		return await self._fetch_list(
			RESOURCE_ALLOCATION_DOCTYPE,
			[
				["allocation_end_date", "=", end_date.isoformat()],
				["project", "is", "set"],
				["status", "=", RESOURCE_ALLOCATION_CONFIRMED_STATUS],
			],
			[
				"name",
				"employee",
				"employee_name",
				"project",
				"project_name",
				"allocation_end_date",
				"hours_allocated_per_day",
				"modified",
			],
		)

	async def get_allocations_starting_between(
		self,
		start: dt.date,
		end: dt.date,
	) -> list[dict]:
		"""Fetch confirmed allocations whose first day falls within [start, end].

		Args:
			start (dt.date): Earliest start date, inclusive.
			end (dt.date): Latest start date, inclusive.

		Returns:
			list[dict]: Records with `name`, `employee`, `project` and
				`allocation_start_date`.

		"""
		return await self._fetch_list(
			RESOURCE_ALLOCATION_DOCTYPE,
			[
				[
					"allocation_start_date",
					"between",
					[start.isoformat(), end.isoformat()],
				],
				["status", "=", RESOURCE_ALLOCATION_CONFIRMED_STATUS],
			],
			["name", "employee", "project", "allocation_start_date"],
		)

	async def get_projects(self, project_ids: list[str]) -> dict[str, dict]:
		"""Map each project ID to its `name`, `status` and project manager.

		Args:
			project_ids (list[str]): Frappe Project `name`s.

		Returns:
			dict[str, dict]: Project ID -> record with `name`, `status` and
				`PROJECT_MANAGER_FIELD`, for projects that exist.

		"""
		if not project_ids:
			return {}

		projects = await self._fetch_list(
			PROJECT_DOCTYPE,
			[["name", "in", project_ids]],
			["name", "status", PROJECT_MANAGER_FIELD],
		)
		return {p["name"]: p for p in projects}

	async def get_project_managers(self, project_ids: list[str]) -> dict[str, str]:
		"""Map each project ID to its project manager's email.

		Args:
			project_ids (list[str]): Frappe Project `name`s.

		Returns:
			dict[str, str]: Project ID -> PM email, for projects that have one.

		"""
		projects = await self.get_projects(project_ids)
		return {
			name: p[PROJECT_MANAGER_FIELD]
			for name, p in projects.items()
			if p.get(PROJECT_MANAGER_FIELD)
		}

	async def get_allocation(self, name: str) -> dict | None:
		"""Fetch a single Resource Allocation document, including its overrides.

		Args:
			name (str): The allocation `name` (e.g. "RA-EMP-00455-2026-0003").

		Returns:
			dict | None: The allocation document, or None if it doesn't exist.

		"""
		try:
			async with httpx.AsyncClient() as client:
				response = await client.get(
					f"{self.base_url}/api/resource/{RESOURCE_ALLOCATION_DOCTYPE}/{name}",
					headers=self.headers,
				)

			if response.status_code == httpx.codes.NOT_FOUND:
				return None

			response.raise_for_status()
			return response.json().get("data")

		except Exception as exc:
			log_and_raise(
				self.logger,
				"Exception occurred while fetching allocation from Frappe",
				exception_type=exc.__class__,
				cause=exc,
			)

	async def extend_allocation(self, allocation: dict, new_end: dt.date) -> None:
		"""Move an existing allocation's end date, keeping every other field.

		Updates the document in place, so ERP's own validation (overlap, leave
		and holidays, totals, cost) runs. Next PMS's `edit_allocation` is
		avoided: on preprod it splits weekends-off ranges into new weekly
		allocations instead of extending this one.

		Args:
			allocation (dict): The current allocation document, as returned
				by `get_allocation`.
			new_end (dt.date): The new allocation end date.

		Raises:
			FrappeValidationError: If Frappe rejects the change (overlap,
				permission, or the allocation changed since it was read).

		"""
		try:
			async with httpx.AsyncClient(timeout=60) as client:
				response = await client.put(
					f"{self.base_url}/api/resource/{RESOURCE_ALLOCATION_DOCTYPE}/"
					f"{allocation['name']}",
					headers=self.headers,
					json={
						# Both dates as strings: validate() compares them.
						"allocation_start_date": allocation["allocation_start_date"],
						"allocation_end_date": new_end.isoformat(),
						# Rejected by Frappe if the allocation changed since read.
						"modified": allocation["modified"],
					},
				)

			if not response.is_client_error:
				response.raise_for_status()

		except Exception as exc:
			log_and_raise(
				self.logger,
				"Exception occurred while extending allocation in Frappe",
				exception_type=exc.__class__,
				cause=exc,
			)

		if response.is_client_error:
			log_and_raise(
				self.logger,
				_frappe_error_message(response),
				exception_type=FrappeValidationError,
			)

	async def add_comment(self, doctype: str, name: str, content: str) -> None:
		"""Add a comment to a document's timeline.

		Args:
			doctype (str): The document's doctype.
			name (str): The document's `name`.
			content (str): Comment text.

		"""
		try:
			async with httpx.AsyncClient() as client:
				response = await client.post(
					f"{self.base_url}/api/resource/{COMMENT_DOCTYPE}",
					headers=self.headers,
					json={
						"comment_type": "Comment",
						"reference_doctype": doctype,
						"reference_name": name,
						"content": content,
					},
				)

			response.raise_for_status()

		except Exception as exc:
			log_and_raise(
				self.logger,
				"Exception occurred while adding comment in Frappe",
				exception_type=exc.__class__,
				cause=exc,
			)
