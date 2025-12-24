"""Constants for GitHub integration."""

# GH access token key name on Redis token store
GITHUB_ACCESS_TOKEN_KEY = "github_access_token"

# Project board status column name for which we will fetch comments
BLOCKED_ISSUE_STATUS_NAME = "Blocked"

# GitHub Service failure max retry limit
GITHUB_SERVICE_FAILURE_MAX_RETRY_LIMIT = 3

# GitHub Data service API rate limit per minute
GITHUB_API_RATE_LIMIT = 10

# Pre-refresh buffer (seconds) for GitHub installation token expiry
GITHUB_ACCESS_TOKEN_REFRESH_BUFFER_SECONDS = 300

# Lock key to coordinate GitHub installation token refresh across workers
GITHUB_TOKEN_REFRESH_LOCK_KEY = "github_access_token_refresh_lock"

# Lock TTL in seconds; should exceed expected token refresh duration
GITHUB_TOKEN_REFRESH_LOCK_TTL_SECONDS = 120
