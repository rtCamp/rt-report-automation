"""Document generation service for Google Docs."""

import logging
from typing import Any

from app.core.config import settings
from app.core.utils import log_and_raise
from app.google_docs.services.folder_manager import FolderManagerService
from app.google_docs.services.google_auth import GoogleAuthService
from app.google_docs.utils.constants import get_template_tag

logger = logging.getLogger(__name__)


class DocGeneratorService:
	"""Service for generating Google Docs from templates."""

	def __init__(self):
		"""Initialize the DocGeneratorService."""
		self.auth_service = GoogleAuthService()
		self.folder_manager = FolderManagerService()

	async def create_doc_from_template(
		self,
		replacements: dict[str, str | list[str]],
		output_name: str,
		parent_folder_id: str,
	) -> str:
		"""Create a Google Doc from a template with replacements.

		Args:
			replacements: Dictionary of key-value pairs for template replacements.
			output_name: Name for the generated document.
			parent_folder_id: Google Drive parent folder ID. The 'Automated Docs'
				folder must already exist within this parent.

		Returns:
			str: URL of the created document.

		Raises:
			ValueError: If output_name is empty, parent_folder_id is empty,
				replacement keys are empty, or template tag keys contain
				invalid characters.
			Exception: If document creation or update fails.

		"""
		# Validate inputs
		if not parent_folder_id:
			log_and_raise(
				logger,
				"parent_folder_id is required and cannot be empty",
			)

		# Validate replacement keys
		for key in replacements:
			if not key or not key.strip():
				log_and_raise(
					logger,
					"Replacement keys cannot be empty",
				)

		# Each call creates a NEW service object with its own httplib2.Http() instance.
		# This ensures thread-safety - even if multiple threads call this method
		# simultaneously, each gets its own service objects.
		drive_service: Any = self.auth_service.get_drive_service()
		docs_service: Any = self.auth_service.get_docs_service()

		# Step 1: Copy the template document
		copy_request_body: dict[str, str | list[str]] = {
			"name": output_name.strip(),
		}

		# Find the automated docs folder within the provided parent folder
		automated_folder_id = await self.folder_manager.get_automated_docs_folder(
			parent_folder_id=parent_folder_id,
		)
		copy_request_body["parents"] = [automated_folder_id]

		try:
			copied_file = (
				drive_service.files()
				.copy(
					fileId=settings.GOOGLE_TEMPLATE_DOC_ID,
					body=copy_request_body,
					supportsAllDrives=True,
				)
				.execute()
			)
		except Exception as e:
			log_and_raise(
				logger,
				"Failed to copy template document. Check folder permissions.",
				Exception,
				e,
			)

		doc_id = copied_file.get("id")

		if not doc_id or not isinstance(doc_id, str):
			log_and_raise(
				logger,
				"Failed to create document copy - no document ID returned",
			)

		# Step 2: Prepare batch update requests for all replacements
		requests = []

		for key, value in replacements.items():
			template_tag = get_template_tag(key)

			# Handle both string and list values
			replace_text = "\n".join(value) if isinstance(value, list) else value

			requests.append(
				{
					"replaceAllText": {
						"containsText": {
							"text": template_tag,
							"matchCase": True,
						},
						"replaceText": replace_text,
					},
				},
			)

		# Step 3: Execute single batch update for all text replacements
		if requests:
			try:
				docs_service.documents().batchUpdate(
					documentId=doc_id,
					body={"requests": requests},
				).execute()
			except Exception as e:
				log_and_raise(
					logger,
					"Failed to update document with replacements. Check template tags.",
					Exception,
					e,
				)

		# Return the document URL
		return f"https://docs.google.com/document/d/{doc_id}/edit"
