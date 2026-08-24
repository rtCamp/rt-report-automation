"""Service for interacting with the Frappe PMS REST API."""

import json
import logging

import httpx

from app.core.config import settings
from app.core.utils import log_and_raise
from app.frappe.constants import (
	DOCSHARE_DOCTYPE,
	GITHUB_REPOSITORY_DOCTYPE,
	NON_BILLABLE_TYPE,
	PROJECT_BILLING_TYPE_FIELD,
	PROJECT_DETAIL_FIELDS,
	PROJECT_DOCTYPE,
	PROJECT_MANAGER_FIELD,
	PROJECT_SUPPRESSED_STATUSES,
	PROJECT_TIMELINE_ITEM_DOCTYPE,
	RISK_DOCTYPE,
	TODO_DOCTYPE,
	USER_DOCTYPE,
)


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

			if response.status_code != 200:
				self.logger.warning(
					"Error fetching project %s: %s %s",
					project_id,
					response.status_code,
					response.text,
				)
				return None

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

		A User's `name` is their email address, and `roles` is a child
		table (`Has Role`) returned inline by the single-document fetch --
		powers the /pms audit command's Delivery Manager override, which
		lets a Delivery Manager audit any project by exact ID even when
		they aren't its PM.

		Args:
			email (str): The user's email (Frappe User `name`).

		Returns:
			list[str]: Role names, e.g. ["Employee", "Delivery Manager"].
				Empty if the user doesn't exist or the lookup fails.

		"""
		try:
			async with httpx.AsyncClient() as client:
				response = await client.get(
					f"{self.base_url}/api/resource/{USER_DOCTYPE}/{email}",
					headers=self.headers,
				)

			if response.status_code != 200:
				self.logger.warning(
					"Error fetching user %s: %s %s",
					email,
					response.status_code,
					response.text,
				)
				return []

			data = response.json().get("data") or {}
			return [row["role"] for row in data.get("roles") or [] if row.get("role")]

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
