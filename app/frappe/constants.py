"""Constants for Frappe PMS integration."""

# Frappe doctype and field used to match a project to its manager's email.
# In Frappe, a User's `name` is their email address, so this Link field
# value IS the manager's email directly.
PROJECT_DOCTYPE = "Project"
PROJECT_MANAGER_FIELD = "custom_project_manager"

# Used by the scheduler-triggered bulk audit (every open, billable project)
# to filter Project records: "billable" means the billing type isn't
# "Non-Billable".
PROJECT_BILLING_TYPE_FIELD = "custom_billing_type"
NON_BILLABLE_TYPE = "Non-Billable"
PROJECT_STATUS_OPEN = "Open"

# Fields reported by the /pms missing-fields command, grouped into sections
# to mirror the Next PMS frontend's project detail layout. Each entry is
# (fieldname, label, icon). "Primary location" is intentionally omitted --
# it isn't a direct Project field (likely comes from the linked Customer).
PROJECT_DETAIL_SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
	(
		"Specifics",
		[
			("priority", "Priority", "📊"),
			("custom_complexity", "Complexity", "🧩"),
			("custom_key_account", "Key Account", "🔑"),
			("custom_host", "Host", "🖥️"),
		],
	),
	(
		"Sourcing",
		[
			("custom_source", "Source", "🔍"),
			("custom_previous_cms", "Previous CMS", "🏷️"),
		],
	),
	(
		"Communication",
		[
			("custom_client_point_of_contact", "Point of Contact", "👤"),
			("frequency", "Time Report Frequency", "📅"),
		],
	),
	(
		"Marketing",
		[
			("custom_restricted_under_nda", "NDA Signed", "🔒"),
			("custom_permission_for_case_study", "Case Study Approved", "📄"),
			("custom_permission_for_testimonial", "Testimonial Approval", "💬"),
			("custom_testimonial_contact", "Testimonial Contact", "📇"),
		],
	),
]

# Check-type (boolean) fields: Frappe stores these as 0/1, and 0 is a real
# "No" rather than a missing value, so they're never flagged as "missing"
# and always render as Yes/No rather than being left blank.
BOOLEAN_FIELDS = {
	"custom_restricted_under_nda",
	"custom_permission_for_case_study",
	"custom_permission_for_testimonial",
}

# Flattened (fieldname, label) pairs across all sections -- used to build
# the Frappe API `fields` param and the compact multi-project missing list.
PROJECT_DETAIL_FIELDS: list[tuple[str, str]] = [
	(fieldname, label)
	for _, fields in PROJECT_DETAIL_SECTIONS
	for fieldname, label, _ in fields
]

# Doctypes backing the /pms audit command.
#
# Milestones: `Project Timeline Item` (module "Next Projects", type="Milestone")
# is the primary source. This is the doctype that powers the ?tab=calendar
# view in Next PMS. Task records with `is_milestone` set are a legacy fallback
# used by some older projects -- the audit queries PTI first and falls back to
# Task-based milestones only if PTI returns nothing.
#
# Todos: come from both `Task` (is_milestone unset) AND the standalone `ToDo`
# doctype (Frappe's generic per-record to-do list, scoped via
# reference_type="Project"/reference_name=<project ID>) -- some projects use
# one, some the other, so both are queried and merged.
#
# Risk is separate and has no due-date field of its own.
PROJECT_TIMELINE_ITEM_DOCTYPE = "Project Timeline Item"
TASK_DOCTYPE = "Task"
TODO_DOCTYPE = "ToDo"
RISK_DOCTYPE = "Risk"
GITHUB_REPOSITORY_DOCTYPE = "GitHub Repository"

TASK_CLOSED_STATUSES = {"Completed", "Cancelled"}
# The ToDo doctype uses its own status vocabulary (Open/Closed/Cancelled)
# rather than Task's -- "Closed" is normalized to "Completed" when merged into a Task
# shaped record so the shared closed-status check above still applies.
TODO_STATUS_TO_TASK_STATUS = {"Closed": "Completed"}
RISK_MITIGATED_STATUS = "Mitigated"
RISK_BLOCKED_STATUS = "Blocked"
# Lower sorts first: escalate High-risk items to the top of the open-risk list.
RISK_LEVEL_ORDER = {"High": 0, "Medium": 1, "Low": 2}
