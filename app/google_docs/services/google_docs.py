"""Google Docs service for document generation."""

import logging

from app.core.utils import log_and_raise
from app.google_docs.services.doc_generator import DocGeneratorService
from app.llm.models.summarization import HoursBreakdownItem

logger = logging.getLogger(__name__)


class GoogleDocsService:
	"""Service for interacting with Google Docs API."""

	def __init__(self):
		"""Initialize the Google Docs service."""
		self.doc_generator = DocGeneratorService()

	async def generate_document(
		self,
		replacements: dict[str, str | list[str]] | None,
		doc_name: str,
		parent_folder_id: str,
		hours_breakdown: list[HoursBreakdownItem] | None = None,
	) -> dict[str, str]:
		"""Generate a Google Doc from template with replacements.

		Args:
			replacements: Dictionary of key-value pairs for template replacements.
				Keys should match template tags (without delimiters).
				Values can be strings or lists of strings.
			doc_name: Name for the generated document.
			parent_folder_id: Google Drive parent folder ID. The 'Automated Docs'
				folder must already exist within this parent.
			hours_breakdown: List of hours breakdown items for detailed reporting.

		Returns:
			dict: Dictionary containing the document URL.
				Example: {"document_url": "https://docs.google.com/document/d/..."}

		Raises:
			ValueError: If replacements is missing or invalid,
				or parent_folder_id is empty.
			Exception: If document generation fails.

		"""
		if replacements is None or not isinstance(replacements, dict):
			log_and_raise(
				logger,
				"Missing or invalid replacements object",
			)

		if not parent_folder_id:
			log_and_raise(
				logger,
				"parent_folder_id is required and cannot be empty",
			)

		document_url = await self.doc_generator.create_doc_from_template(
			replacements=replacements,
			output_name=doc_name,
			parent_folder_id=parent_folder_id,
			hours_breakdown=hours_breakdown,
		)

		return {"document_url": document_url}
