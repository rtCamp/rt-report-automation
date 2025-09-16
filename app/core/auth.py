"""Authentication utilities."""

import secrets

from fastapi import Security
from fastapi.security import api_key

from app.core.config import settings
from app.core.exceptions import AuthenticationError

api_key_header = api_key.APIKeyHeader(name="X-API-KEY")


def validate_api_key(key: str = Security(api_key_header)):
	"""Validate the provided API key against the configured key.

	Args:
		key (str): The API key provided in the request header.

	Raises:
		AuthenticationError: If the API key is invalid.

	Returns:
		str: The validated API key.

	"""
	if not secrets.compare_digest(key, settings.APP_API_KEY.get_secret_value()):
		raise AuthenticationError(message="Invalid API Key")
	return key
