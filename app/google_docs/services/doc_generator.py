"""Document generation service for Google Docs."""

import logging
from typing import Any

from app.core.config import settings
from app.core.utils import log_and_raise
from app.google_docs.services.google_auth import GoogleAuthService
from app.google_docs.utils.constants import get_template_tag

logger = logging.getLogger(__name__)


class DocGeneratorService:
	"""Service for generating Google Docs from templates."""

	def __init__(self):
		"""Initialize the DocGeneratorService."""
		self.auth_service = GoogleAuthService()

	async def create_doc_from_template(
		self,
		replacements: dict[str, str | list[str]],
		output_name: str,
	) -> str:
		"""Create a Google Doc from a template with replacements.

		Args:
			replacements: Dictionary of key-value pairs for template replacements.
			output_name: Name for the generated document.

		Returns:
			str: URL of the created document.

		Raises:
			ValueError: If output_name is empty, replacement keys are empty,
				or template tag keys contain invalid characters.
			Exception: If document creation or update fails.

		"""
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

		# Add output folder if configured
		# If not set, document will be copied to the template's parent folder
		if settings.GOOGLE_OUTPUT_FOLDER_ID:
			copy_request_body["parents"] = [settings.GOOGLE_OUTPUT_FOLDER_ID]

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
