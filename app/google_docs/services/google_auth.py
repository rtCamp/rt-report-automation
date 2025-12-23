"""Authentication service for Google Workspace using Service Account."""

import json

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build

from app.core.config import settings


class GoogleAuthService:
	"""Service for authenticating with Google Workspace using service account."""

	def __init__(self):
		"""Initialize the GoogleAuthService."""
		self._credentials = None

	def _get_credentials(self) -> service_account.Credentials:
		"""Get or create service account credentials.

		Returns:
			service_account.Credentials: Google service account credentials.

		Raises:
			ValueError: If service account key is invalid.

		"""
		if self._credentials is None:
			try:
				# Parse the service account key JSON
				service_account_info = json.loads(
					settings.GOOGLE_SERVICE_ACCOUNT_KEY.get_secret_value(),
				)

				# Create credentials from service account info
				creds = service_account.Credentials
				self._credentials = creds.from_service_account_info(
					service_account_info,
					scopes=settings.google_scopes_list,
				)

			except json.JSONDecodeError as e:
				raise ValueError("Invalid service account key format") from e
			except KeyError as e:
				error_msg = f"Service account key missing required field: {e}"
				raise ValueError(error_msg) from e

		return self._credentials

	def get_drive_service(self):
		"""Get an authenticated Google Drive service.

		Returns:
			Resource: Google Drive API service.

		"""
		credentials = self._get_credentials()

		# Service account credentials need to be refreshed to get access token
		if not credentials.valid or not credentials.token:
			credentials.refresh(Request())

		return build("drive", "v3", credentials=credentials)

	def get_docs_service(self):
		"""Get an authenticated Google Docs service.

		Returns:
			Resource: Google Docs API service.

		"""
		credentials = self._get_credentials()

		# Service account credentials need to be refreshed to get access token
		if not credentials.valid or not credentials.token:
			credentials.refresh(Request())

		return build("docs", "v1", credentials=credentials)
