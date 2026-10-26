"""Constants for Slack integration."""

# Allow 2 executions/minute - may occasionally hit conversations.replies
# 50+ RPM limit (60 calls total) but burst behavior should handle it.
SLACK_API_RATE_LIMIT = 2

# Echoed back by Slack on options requests and selections, so the interaction
# handler can tell this menu apart from any future one.
AUDIT_PROJECT_SELECT_ACTION_ID = "audit_project_select"

ALLOCATION_EXTEND_ACTION_ID = "allocation_extend"
ALLOCATION_DECLINE_ACTION_ID = "allocation_decline"
ALLOCATION_DAYS_BLOCK_ID = "allocation_extend_days"
ALLOCATION_DAYS_ACTION_ID = "allocation_extend_days_input"
ALLOCATION_EXTEND_CALLBACK_ID = "allocation_extend_modal"
ALLOCATION_VIEW_PROJECT_ACTION_ID = "allocation_view_project"

# Reminded every weekday from this many days before the end date until the
# allocation is extended, removed, or the employee is fully booked elsewhere.
ALLOCATION_REMINDER_LEAD_DAYS = 14
ALLOCATION_TIMEZONE = "Asia/Kolkata"
ALLOCATION_REMINDER_CRON = f"TZ={ALLOCATION_TIMEZONE} 0 8 * * 1-5"
# Next PMS splits weekends-off bookings into weekly allocations, so one followed
# by another for the same employee and project within this window isn't ending.
ALLOCATION_CONTINUATION_WINDOW_DAYS = 7
ALLOCATION_EXTEND_MAX_DAYS = 365

ALLOCATION_REMINDED_KEY = "allocation:reminded:{name}:{end_date}:{sent_on}"
ALLOCATION_REMINDED_TTL = 86400 * (ALLOCATION_REMINDER_LEAD_DAYS + 1)
# One decision (extend or decline) per reminder; Yes and No race for it.
ALLOCATION_DECISION_KEY = "allocation:decision:{name}:{end_date}:{sent_on}"
# The allocation's reminder that still has buttons, replaced by the next one.
ALLOCATION_LIVE_REMINDER_KEY = "allocation:live_reminder:{name}"
# Which run wrote an extension against a given allocation revision, so a
# retry of that run can tell its own write from someone else's edit.
ALLOCATION_APPLIED_KEY = "allocation:extend_applied:{name}:{revision}"
ALLOCATION_EXTEND_LOCK_KEY = "allocation:extend_lock:{name}"
ALLOCATION_EXTEND_LOCK_TTL = 300

# Slack rejects the whole Block Kit payload if either is exceeded.
SLACK_OPTION_TEXT_LIMIT = 75
SLACK_MAX_SELECT_OPTIONS = 100

# Slack drops the options response at 3s; stay under it so a slow upstream
# yields an empty menu rather than nothing at all.
OPTIONS_TIME_BUDGET_SECONDS = 2.5

# /pms subcommands, and the usage text shown for anything else.
PMS_SUBCOMMANDS = frozenset({"projects", "missing-fields", "audit"})
PMS_USAGE_TEXT = (
	"Usage: `/pms projects`, `/pms missing-fields`, or `/pms audit`. "
	"`missing-fields` can optionally take a project name or ID to filter to a "
	"single project, e.g. `/pms missing-fields PROJ-0669`. `audit` opens a "
	"project picker, or takes an ID directly, e.g. `/pms audit PROJ-0669`."
)

# A user ID maps to the same email indefinitely; cached to keep the lookup
# off the picker's per-keystroke path.
SLACK_USER_EMAIL_CACHE_KEY = "slack:user_email:{user_id}"
SLACK_USER_EMAIL_CACHE_TTL = 86400

# Legacy workflow name. Standup threads are now matched on the "standup" and
# "tracker" keywords in SlackService._filter_messages_by_workflow, so this
# exact name only still matters as a fallback for older messages posted
# before the naming was standardized.
STANDUP_WORKFLOW_NAME = "AI Internal - Daily Tasks Tracker"

# Standardized question keys - always in the same order
STANDARD_QUESTIONS = [
	"yesterday",
	"today",
	"blockers",
	"demo",
]

# Keyword anchors used to detect standup sections in legacy/old-format threads
# that do not contain NEW_FORMAT_IDENTIFIER. Matching is case-insensitive and
# checks whether a line contains any of these keywords as a section header.
KEYWORD_ANCHORS: dict[str, list[str]] = {
	"yesterday": ["yesterday"],
	"today": ["today"],
	"blockers": ["blocker", "blockers"],
	"demo": ["demo"],
}

# Parser thresholds (all measured in characters).
STANDUP_MIN_QUESTION_LINE_LENGTH = 10
STANDUP_MAX_HEADER_MATCH_OFFSET = 15
STANDUP_LONG_LINE_LENGTH_THRESHOLD = 100

# ============================================================================
# New Format Constants
# ============================================================================

# New format identifier - messages starting with this are in the new format
NEW_FORMAT_IDENTIFIER = "# Daily update from"

# New format question patterns
NEW_FORMAT_PATTERNS = {
	"yesterday": ["what did you work on yesterday"],
	"today": ["what will you be working on today"],
	"blockers": ["any blockers encountered"],
	"demo": ["anything youd like to demo internally"],
}

# Old format question patterns (DEPRECATED)
OLD_FORMAT_PATTERNS = {
	"yesterday": [
		"what you worked on yesterday",
		"what did you work on yesterday",
	],
	"today": [
		"what are you working on today",
		"what you are working on today",
	],
	"blockers": [
		"any blockers encountered or conversations needed",
		"any blockers encountered of conversations needed",
		"any blockers to conversations needed",
	],
	"demo": [
		"anything youd like to demo internally",
	],
}

# Combined patterns for backward compatibility (will be removed in future)
# Use NEW_FORMAT_PATTERNS or OLD_FORMAT_PATTERNS instead
QUESTION_PATTERNS = {
	key: list(
		dict.fromkeys(
			NEW_FORMAT_PATTERNS.get(key, []) + OLD_FORMAT_PATTERNS.get(key, [])
		),
	)
	for key in set(NEW_FORMAT_PATTERNS) | set(OLD_FORMAT_PATTERNS)
}
