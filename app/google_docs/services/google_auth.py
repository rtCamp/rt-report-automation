"""Authentication service for Google Workspace using Service Account."""

import json
import threading

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import Resource, build

from app.core.config import settings


class GoogleAuthService:
	"""Service for authenticating with Google Workspace using service account.

	This service is thread-safe. Credentials are cached per-thread using
	thread-local storage.
	"""

	def __init__(self):
		"""Initialize the GoogleAuthService."""
		self._local = threading.local()

	def _get_credentials(self) -> service_account.Credentials:
		"""Get or create service account credentials.

		Credentials are cached per-thread for performance while maintaining
		thread-safety.

		Returns:
			service_account.Credentials: Google service account credentials.

		Raises:
			ValueError: If service account key is invalid.

		"""
		# Get or create credentials for this thread
		if not hasattr(self._local, "credentials"):
			try:
				# Parse the service account key JSON
				service_account_info = json.loads(
					settings.GOOGLE_SERVICE_ACCOUNT_KEY.get_secret_value(),
				)

				# Create credentials from service account info
				creds = service_account.Credentials
				self._local.credentials = creds.from_service_account_info(
					service_account_info,
					scopes=settings.google_scopes_list,
				)

			except json.JSONDecodeError as e:
				raise ValueError("Invalid service account key format") from e
			except KeyError as e:
				error_msg = f"Service account key missing required field: {e}"
				raise ValueError(error_msg) from e

		# Ensure cached credentials are valid before returning
		credentials = self._local.credentials
		if not credentials.valid or not credentials.token:
			try:
				credentials.refresh(Request())
			except Exception as e:
				raise ValueError(
					f"Failed to refresh service account credentials: {e}",
				) from e

		return credentials

	def get_drive_service(self) -> Resource:
		"""Get an authenticated Google Drive service.

		Returns:
			Resource: Google Drive API service.

		Raises:
			ValueError: If credentials are invalid or refresh fails.

		"""
		credentials = self._get_credentials()
		return build("drive", "v3", credentials=credentials)

	def get_docs_service(self) -> Resource:
		"""Get an authenticated Google Docs service.

		Returns:
			Resource: Google Docs API service.

		Raises:
			ValueError: If credentials are invalid or refresh fails.

		"""
		credentials = self._get_credentials()
		return build("docs", "v1", credentials=credentials)
