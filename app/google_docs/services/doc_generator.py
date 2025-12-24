"""Document generation service for Google Docs."""

import logging
from typing import Any

from app.core.config import settings
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
			Exception: If document creation or update fails.

		"""
		# Each call creates a NEW service object with its own httplib2.Http() instance.
		# This ensures thread-safety - even if multiple threads call this method
		# simultaneously, each gets its own service objects.
		drive_service: Any = self.auth_service.get_drive_service()
		docs_service: Any = self.auth_service.get_docs_service()

		try:
			# Step 1: Copy the template document
			copy_request_body: dict[str, str | list[str]] = {"name": output_name}

			if settings.GOOGLE_OUTPUT_FOLDER_ID:
				try:
					# Try to use specified output folder
					copy_request_body["parents"] = [settings.GOOGLE_OUTPUT_FOLDER_ID]
				except Exception as e:
					logger.error(f"Failed to add output folder: {e}")

			copied_file = (
				drive_service.files()
				.copy(
					fileId=settings.GOOGLE_TEMPLATE_DOC_ID,
					body=copy_request_body,
					supportsAllDrives=True,
				)
				.execute()
			)

			doc_id = copied_file.get("id")

			if not doc_id:
				raise Exception(
					"Failed to create document copy - no document ID returned",
				)

			logger.info(f"Document copied successfully: {doc_id}")

			# Step 2: Prepare batch update requests for all replacements
			requests = []

			for key, value in replacements.items():
				template_tag = get_template_tag(key)

				# Handle both string and list values
				replace_text = isinstance(value, list) and "\n".join(value) or value

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
				docs_service.documents().batchUpdate(
					documentId=doc_id,
					body={"requests": requests},
				).execute()
				logger.info("Batch update completed successfully")

			# Return the document URL
			document_url = f"https://docs.google.com/document/d/{doc_id}/edit"
			logger.info(f"Document generated successfully: {document_url}")

			return document_url

		except Exception as e:
			logger.error(f"Error generating document: {e}")
			raise
