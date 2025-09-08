import redis

from app.core.config import settings


def get_redis_client() -> redis.Redis:
	return redis.Redis(
		host=settings.REDIS_HOST,
		port=settings.REDIS_PORT,
		db=0,
		password=settings.REDIS_PASSWORD.get_secret_value() or None,
	)


redis_client = get_redis_client()
