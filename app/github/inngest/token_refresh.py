"""Inngest function to proactively refresh GitHub installation token."""

import inngest

from app.core.adapters.inngest import inngest_client
from app.core.adapters.redis import redis_client
from app.github.services.github_auth import GitHubAuthService
from app.github.utils.constants import (
	GITHUB_ACCESS_TOKEN_KEY,
	GITHUB_ACCESS_TOKEN_REFRESH_BUFFER_SECONDS,
	GITHUB_TOKEN_REFRESH_LOCK_KEY,
	GITHUB_TOKEN_REFRESH_LOCK_TTL_SECONDS,
)


@inngest_client.create_function(
	fn_id="refresh_github_access_token",
	trigger=inngest.TriggerCron(cron="*/2 * * * *"),  # every 2 minute
)
async def refresh_github_access_token(ctx: inngest.Context) -> dict:
	"""Proactively refresh GitHub installation access token if nearing expiry.

	Args:
		ctx (inngest.Context): Inngest function context.

	Raises:
		Exception: If token refresh fails.

	Returns:
		dict: Status of the token refresh operation.

	"""
	ttl = redis_client.ttl(GITHUB_ACCESS_TOKEN_KEY)

	# If token missing (-2) or expiring within buffer, attempt refresh
	if (
		ttl == -2
		or (
			ttl != -1
			and ttl <= GITHUB_ACCESS_TOKEN_REFRESH_BUFFER_SECONDS
		)
	):
		# Acquire a short-lived lock so only one worker refreshes
		have_lock = redis_client.set(
			GITHUB_TOKEN_REFRESH_LOCK_KEY,
			"1",
			nx=True,
			ex=GITHUB_TOKEN_REFRESH_LOCK_TTL_SECONDS,
		)

		if not have_lock:
			return {"status": "skipped", "reason": "lock_held"}

		try:
			auth = GitHubAuthService()
			await auth.get_access_token(force_refresh=True)
			return {"status": "refreshed"}
		except Exception as e:  # noqa: BLE001 - surface to Inngest logs
			ctx.logger.error(f"Token refresh failed: {e}")
			raise
	else:
		return {"status": "healthy", "ttl": ttl}
