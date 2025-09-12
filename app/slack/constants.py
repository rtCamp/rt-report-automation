# Allow 2 executions/minute - may occasionally hit conversations.replies
# 50+ RPM limit (60 calls total) but burst behavior should handle it.
SLACK_API_RATE_LIMIT = 2

# TODO(sainathpoojary): https://github.com/rtCamp/rt-report-automation/issues/11
# After standardizing the workflow name, update it here.
STANDUP_WORKFLOW_NAME = "AI Internal - Daily Tasks Tracker"
