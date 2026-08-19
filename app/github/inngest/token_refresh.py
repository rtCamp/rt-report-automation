"""Inngest function to proactively refresh GitHub installation token."""

from typing import cast

import inngest

from app.core.adapters.inngest import inngest_client
from app.core.adapters.redis import redis_client
from app.github.services.github_auth import GitHubAuthService
from app.github.utils.constants import (
	GITHUB_ACCESS_TOKEN_KEY,
	GITHUB_ACCESS_TOKEN_REFRESH_BUFFER_SECONDS,
)


@inngest_client.create_function(
	fn_id="refresh_github_access_token",
	trigger=inngest.TriggerCron(cron="*/7 * * * *"),  # every 7 minutes
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
	ttl = cast(int, redis_client.ttl(GITHUB_ACCESS_TOKEN_KEY))  # noqa: TC006

	# If token missing (-2), has no expiry set (-1),
	# or is expiring within buffer, attempt refresh
	if ttl == -2 or (ttl != -1 and ttl <= GITHUB_ACCESS_TOKEN_REFRESH_BUFFER_SECONDS):
		try:
			auth = GitHubAuthService()
			await auth.get_access_token(force_refresh=True)
			return {"status": "refreshed"}
		except Exception as e:
			ctx.logger.error(f"Token refresh failed: {e}")
			raise
	else:
		return {"status": "healthy", "ttl": ttl}
