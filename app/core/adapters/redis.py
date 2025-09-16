"""Redis adapter module."""

from redis import Redis
from redis.exceptions import AuthenticationError, ConnectionError

from app.core.config import settings
from app.core.exceptions import InternalServerError


def get_redis_client() -> Redis:
	"""Get a Redis client instance.

	Returns:
		Redis: A connected Redis client instance.

	"""
	try:
		client = Redis(
			host=settings.REDIS_HOST,
			port=settings.REDIS_PORT,
			db=0,
			password=settings.REDIS_PASSWORD.get_secret_value() or None,
			decode_responses=True,
		)
		client.ping()
		return client
	except (ConnectionError, AuthenticationError) as e:
		raise InternalServerError(e, "Redis connection error", "Check Redis env")


redis_client = get_redis_client()
