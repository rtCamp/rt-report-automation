import secrets

from fastapi import Security
from fastapi.security import api_key

from app.core.config import settings
from app.core.exceptions import AuthenticationError

api_key_header = api_key.APIKeyHeader(name="X-API-KEY")


def validate_api_key(key: str = Security(api_key_header)):
	if not secrets.compare_digest(key, settings.APP_API_KEY.get_secret_value()):
		raise AuthenticationError(message="Invalid API Key")
	return key
