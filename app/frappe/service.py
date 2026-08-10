"""Service for interacting with the Frappe PMS REST API."""

import json
import logging

import httpx

from app.core.config import settings
from app.core.utils import log_and_raise
from app.frappe.constants import (
	GITHUB_REPOSITORY_DOCTYPE,
	NON_BILLABLE_TYPE,
	PROJECT_BILLING_TYPE_FIELD,
	PROJECT_DETAIL_FIELDS,
	PROJECT_DOCTYPE,
	PROJECT_MANAGER_FIELD,
	PROJECT_STATUS_OPEN,
	PROJECT_TIMELINE_ITEM_DOCTYPE,
	RISK_DOCTYPE,
	TASK_DOCTYPE,
	TODO_DOCTYPE,
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
				``PROJECT_DETAIL_FIELDS``. Empty if none match or the
				lookup fails.

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

			if response.status_code != 200:
				self.logger.warning(
					"Error fetching projects for %s: %s %s",
					email,
					response.status_code,
					response.text,
				)
				return []

			return response.json().get("data", [])

		except Exception as exc:
			log_and_raise(
				self.logger,
				"Exception occurred while fetching projects from Frappe",
				exception_type=exc.__class__,
				cause=exc,
			)

	async def get_billable_open_projects(
		self,
		manager_emails: list[str] | None = None,
	) -> list[dict]:
		"""Fetch every open, billable project, for the scheduler-triggered bulk audit.

		Unlike `get_projects_by_manager_email`, this isn't scoped to a known
		manager -- it fetches `PROJECT_MANAGER_FIELD` (the PM's email)
		directly in the results so the caller can route each project's
		audit to the right person.

		Args:
			manager_emails (list[str] | None): When set, restricts to
				projects managed by any of these emails -- used to scope
				test runs to a handful of people's projects rather than
				the whole company.

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
			["status", "=", PROJECT_STATUS_OPEN],
			[PROJECT_BILLING_TYPE_FIELD, "!=", NON_BILLABLE_TYPE],
		]
		if manager_emails:
			filters.append([PROJECT_MANAGER_FIELD, "in", manager_emails])
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
			list[dict]: Matching records. Empty if none match or the
				lookup fails.

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

			if response.status_code != 200:
				self.logger.warning(
					"Error fetching %s: %s %s",
					doctype,
					response.status_code,
					response.text,
				)
				return []

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

	async def get_tasks_by_project(self, project_id: str) -> list[dict]:
		"""Fetch all Task records (todos and legacy is_milestone tasks) for a project.

		Args:
			project_id (str): The Frappe Project `name`.

		Returns:
			list[dict]: Task records with `name`, `subject`, `status`,
				`is_milestone`, `exp_end_date`, and `priority`.

		"""
		return await self._fetch_list(
			TASK_DOCTYPE,
			[["project", "=", project_id]],
			["name", "subject", "status", "is_milestone", "exp_end_date", "priority"],
		)

	async def get_todos_by_project(self, project_id: str) -> list[dict]:
		"""Fetch standalone ToDo records (Frappe's generic to-do list) for a project.

		Distinct from `get_tasks_by_project`: some projects track todos as
		`Task` records, others via this generic, doctype-agnostic ToDo
		list (linked here through `reference_type`/`reference_name` rather
		than a `project` field), so both are queried and merged.

		Args:
			project_id (str): The Frappe Project `name`.

		Returns:
			list[dict]: ToDo records with `name`, `description`, `status`,
				and `date` (the due date, may be None).

		"""
		return await self._fetch_list(
			TODO_DOCTYPE,
			[
				["reference_type", "=", PROJECT_DOCTYPE],
				["reference_name", "=", project_id],
			],
			["name", "description", "status", "date"],
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
