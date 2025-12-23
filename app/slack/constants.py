"""Constants for Slack integration."""

# Allow 2 executions/minute - may occasionally hit conversations.replies
# 50+ RPM limit (60 calls total) but burst behavior should handle it.
SLACK_API_RATE_LIMIT = 2
