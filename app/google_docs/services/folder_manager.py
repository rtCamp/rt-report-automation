"""Folder management service for Google Drive."""

import logging
from typing import Any

from googleapiclient.errors import HttpError

from app.core.utils import log_and_raise
from app.google_docs.services.google_auth import GoogleAuthService
from app.google_docs.utils.constants import AUTOMATED_DOCS_FOLDER_NAME

logger = logging.getLogger(__name__)


class FolderManagerService:
	"""Service for managing folders in Google Drive."""

	def __init__(self):
		"""Initialize the FolderManagerService."""
		self.auth_service = GoogleAuthService()

	def _search_folder_recursive(
		self,
		drive_service: Any,
		parent_folder_id: str,
		target_folder_name: str,
		visited_folders: set[str] | None = None,
	) -> str | None:
		"""Recursively search for a folder by name in a folder tree.

		Args:
			drive_service: Google Drive API service instance.
			parent_folder_id: ID of the folder to start searching from.
			target_folder_name: Name of the folder to find.
			visited_folders: Set of already visited folder IDs to prevent cycles.

		Returns:
			str | None: Folder ID if found, None otherwise.

		"""
		if visited_folders is None:
			visited_folders = set()

		# Prevent infinite loops from circular references
		if parent_folder_id in visited_folders:
			return None

		visited_folders.add(parent_folder_id)

		try:
			# Query for folders within the parent folder
			query = (
				f"'{parent_folder_id}' in parents "
				f"and mimeType = 'application/vnd.google-apps.folder' "
				f"and trashed = false"
			)

			results = (
				drive_service.files()
				.list(
					q=query,
					fields="files(id, name)",
					supportsAllDrives=True,
					includeItemsFromAllDrives=True,
				)
				.execute()
			)

			files = results.get("files", [])

			# Check if any child folder matches the target name
			for file in files:
				if file.get("name") == target_folder_name:
					return file.get("id")

			# Recursively search in child folders
			for file in files:
				file_id = file.get("id")
				if not file_id:
					continue

				folder_id = self._search_folder_recursive(
					drive_service=drive_service,
					parent_folder_id=file_id,
					target_folder_name=target_folder_name,
					visited_folders=visited_folders,
				)
				if folder_id:
					return folder_id

		except HttpError as e:
			# Log warning for permission/access issues but continue searching
			if e.resp.status in [403, 404]:
				logger.warning(
					f"Access denied or folder not found {parent_folder_id}: {e}",
				)
			else:
				logger.warning(
					f"Error searching in folder {parent_folder_id}: {e}",
				)
		except Exception as e:
			# Log unexpected errors but continue searching
			logger.warning(
				f"Unexpected error searching in folder {parent_folder_id}: {e}",
			)

		return None

	async def get_automated_docs_folder(
		self,
		parent_folder_id: str,
	) -> str:
		"""Get the automated docs folder.

		This method implements Recursive child discovery:
		- Recursively searches for a folder with the predefined name
		- Returns the folder ID if found
		- Raises an error if not found

		Args:
			parent_folder_id: ID of the parent folder to search from.

		Returns:
			str: ID of the found automated docs folder.

		Raises:
			Exception: If folder is not found or API call errors occur.

		"""
		drive_service = self.auth_service.get_drive_service()

		# Try to find the folder recursively
		folder_id = self._search_folder_recursive(
			drive_service=drive_service,
			parent_folder_id=parent_folder_id,
			target_folder_name=AUTOMATED_DOCS_FOLDER_NAME,
		)

		# If not found, raise an error
		if not folder_id:
			log_and_raise(
				logger,
				f"Folder '{AUTOMATED_DOCS_FOLDER_NAME}' not found in parent "
				f"folder {parent_folder_id} or its children. "
				f"Please create the folder manually.",
			)

		return folder_id
