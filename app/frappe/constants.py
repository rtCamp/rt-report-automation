"""Constants for Frappe PMS integration."""

# Frappe doctype and field used to match a project to its manager's email.
# In Frappe, a User's `name` is their email address, so this Link field
# value IS the manager's email directly.
PROJECT_DOCTYPE = "Project"
PROJECT_MANAGER_FIELD = "custom_project_manager"
# Labeled "Lead Engineer" in the Next PMS UI, "Engineering Manager" in Frappe.
PROJECT_ENGINEERING_MANAGER_FIELD = "custom_engineering_manager"

# Frappe role that grants /pms audit access to any project by exact ID, even
# when the requester isn't that project's PM. Confirmed to exist via the
# live Role doctype (alongside "Delivery User").
DELIVERY_MANAGER_ROLE = "Delivery Manager"
USER_DOCTYPE = "User"

# Used by the scheduler-triggered bulk audit (every open, billable project)
# to filter Project records: "billable" means the billing type isn't
# "Non-Billable".
PROJECT_BILLING_TYPE_FIELD = "custom_billing_type"
NON_BILLABLE_TYPE = "Non-Billable"

# Statuses excluded from the scheduler-triggered bulk audit -- these
# projects are inactive/non-operational, so proactively auditing and DMing
# their PM would just be noise. Deny-list rather than an allow-list (this
# previously hard-coded status == "Open" only) so any other active status
# value still gets audited. On-demand /pms commands are unaffected -- a PM
# can still explicitly query any of their own projects regardless of status.
#
# Confirmed against the live Project doctype's `status` Select field
# options: "Open", "On hold" (lowercase h), "Completed", "Cancelled" --
# that's the full set, no "Archived"/"Internal" status exists in this
# instance. "Internal" (non-client) projects are identified via
# `custom_billing_type == "Non-Billable"` instead, which the bulk audit
# already filters out separately (see `NON_BILLABLE_TYPE` below).
PROJECT_SUPPRESSED_STATUSES = {"On hold", "Completed", "Cancelled"}

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
			("custom_permission_for_case_study", "Case Study Approved", "📄"),
		],
	),
]

# Check-type (boolean) fields: Frappe stores these as 0/1, and 0 is a real
# "No" rather than a missing value, so they're never flagged as "missing"
# and always render as Yes/No rather than being left blank.
BOOLEAN_FIELDS = {
	"custom_permission_for_case_study",
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
# is the sole source. This is the doctype that powers the ?tab=calendar view
# in Next PMS.
#
# Todos: come exclusively from the standalone `ToDo` doctype (Frappe's
# generic per-record to-do list, scoped via
# reference_type="Project"/reference_name=<project ID>).
#
# Risk is separate and has no due-date field of its own.
PROJECT_TIMELINE_ITEM_DOCTYPE = "Project Timeline Item"
TODO_DOCTYPE = "ToDo"
RISK_DOCTYPE = "Risk"
GITHUB_REPOSITORY_DOCTYPE = "GitHub Repository"

# Next PMS has no dedicated "team members" field -- the Members panel's team
# list is derived from Frappe's document sharing (`DocShare`): everyone the
# Project record is shared with, minus the PM and Lead Engineer (who are
# shared too, but surfaced as their own roles rather than generic members).
DOCSHARE_DOCTYPE = "DocShare"

# Retainer classification -- Project.custom_billing_type value set.
RETAINER_BILLING_TYPE = "Retainer"
FIXED_COST_BILLING_TYPE = "Fixed Cost"
TIME_AND_MATERIAL_BILLING_TYPE = "Time and Material"

# Project billing team: child table on Project listing the billable team
# members (distinct from Resource Allocation, which covers all resourcing,
# billable or not).
PROJECT_BILLING_TEAM_FIELD = "custom_project_billing_team"
PROJECT_BILLING_TEAM_DOCTYPE = "Project Billing Team"

# Project budget: child table on Project tracking purchased/consumed/
# remaining hours per budget period. Shown as "Contracts" in the Next PMS
# Tracking tab -- backs the retainer-hours-consumed and budget-burn checks.
PROJECT_BUDGET_FIELD = "custom_project_budget_hours"
PROJECT_BUDGET_DOCTYPE = "Project Budget"

# Contract value: standard ERPNext field computed from Sales Orders, plus
# custom lifetime-value fields tracked separately on Project. Shown as
# "Total project value" in the Next PMS UI.
CONTRACT_VALUE_FIELD = "total_sales_amount"
LIFETIME_VALUE_TO_DATE_FIELD = "custom_lifetime_value_to_date"
EXPECTED_LIFETIME_VALUE_FIELD = "custom_expected_lifetime_value"
LIFETIME_VALUE_VS_BILLED_FIELD = "custom_lifetime_value_vs_billed_amount"

TASK_CLOSED_STATUSES = {"Completed", "Cancelled"}
# The ToDo doctype uses its own status vocabulary (Open/Closed/Cancelled)
# rather than Task's -- "Closed" is normalized to "Completed" when merged into a Task
# shaped record so the shared closed-status check above still applies.
TODO_STATUS_TO_TASK_STATUS = {"Closed": "Completed"}
RISK_MITIGATED_STATUS = "Mitigated"
RISK_BLOCKED_STATUS = "Blocked"
# Lower sorts first: escalate High-risk items to the top of the open-risk list.
RISK_LEVEL_ORDER = {"High": 0, "Medium": 1, "Low": 2}
