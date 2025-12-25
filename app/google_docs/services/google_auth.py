"""Authentication service for Google Workspace using service account."""

import json
import logging

from google.auth import exceptions as auth_exceptions
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import Resource, build

from app.core.config import settings
from app.core.utils import log_and_raise

logger = logging.getLogger(__name__)


class GoogleAuthService:
	"""Service for authenticating with Google Workspace using service account.

	Thread-safety notes:
		- Credentials are cached and shared across calls (thread-safe).
		- Service objects (Resource) are created fresh on each call.
		- Do NOT share returned service objects across threads, as httplib2.Http()
		is not thread-safe. Call get_drive_service() or get_docs_service() in
		each thread that needs them.
	"""

	def __init__(self):
		"""Initialize the GoogleAuthService."""
		self._credentials: service_account.Credentials | None = None

	def _get_credentials(self) -> service_account.Credentials:
		"""Get or create service account credentials.

		Credentials are cached at the instance level. The underlying Credentials
		object from google-auth is thread-safe and handles concurrent access
		internally.

		Returns:
			service_account.Credentials: Service account credentials for Google APIs.

		Raises:
			ValueError: If service account key is invalid.

		"""
		# Create credentials if not already cached
		if self._credentials is None:
			try:
				# Parse the service account key JSON
				service_account_info = json.loads(
					settings.GOOGLE_SERVICE_ACCOUNT_KEY.get_secret_value(),
				)

				# Create credentials from service account info
				credentials = service_account.Credentials
				self._credentials = credentials.from_service_account_info(
					service_account_info,
					scopes=settings.google_scopes_list,
				)

			except json.JSONDecodeError as e:
				log_and_raise(
					logger,
					"Invalid service account key format",
					ValueError,
					e,
				)
			except KeyError as e:
				log_and_raise(
					logger,
					f"Service account key missing required field: {e}",
					ValueError,
					e,
				)

		# Ensure cached credentials are valid before returning
		if not self._credentials.valid or not self._credentials.token:
			try:
				self._credentials.refresh(Request())
			except auth_exceptions.RefreshError as e:
				log_and_raise(
					logger,
					"Failed to refresh service account credentials",
					ValueError,
					e,
				)

		return self._credentials

	def get_drive_service(self) -> Resource:
		"""Get an authenticated Google Drive API service.

		Creates a new service instance on each call. While credentials are reused
		(thread-safe), each service object has its own httplib2.Http() instance.

		Warning:
			The returned Resource object should NOT be shared across threads.
			The underlying httplib2.Http() is not thread-safe. Each thread should
			call this method to get its own service instance.

		Returns:
			Resource: Google Drive API service.

		Raises:
			ValueError: If credentials are invalid or refresh fails.

		"""
		credentials = self._get_credentials()
		return build("drive", "v3", credentials=credentials)

	def get_docs_service(self) -> Resource:
		"""Get an authenticated Google Docs API service.

		Creates a new service instance on each call. While credentials are reused
		(thread-safe), each service object has its own httplib2.Http() instance.

		Warning:
			The returned Resource object should NOT be shared across threads.
			The underlying httplib2.Http() is not thread-safe. Each thread should
			call this method to get its own service instance.

		Returns:
			Resource: Google Docs API service.

		Raises:
			ValueError: If credentials are invalid or refresh fails.

		"""
		credentials = self._get_credentials()
		return build("docs", "v1", credentials=credentials)
