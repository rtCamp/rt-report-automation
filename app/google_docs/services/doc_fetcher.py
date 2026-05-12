"""Service for fetching Google Doc content as Markdown."""

import logging
from typing import Any

import html2text

from app.core.utils import log_and_raise
from app.google_docs.services.google_auth import GoogleAuthService
from app.google_docs.utils.helpers import extract_doc_id_from_url

logger = logging.getLogger(__name__)


class DocFetcherService:
	"""Service for fetching Google Doc content and converting to Markdown."""

	def __init__(self):
		"""Initialize the DocFetcherService."""
		self.auth_service = GoogleAuthService()

	async def fetch_doc_as_markdown(self, doc_url: str) -> str:
		"""Fetch a Google Doc and return its content as Markdown.

		Uses the Google Drive API to export the document as HTML,
		then converts it to Markdown for token-efficient LLM consumption.

		Args:
			doc_url: Full Google Docs URL.

		Returns:
			str: Document content in Markdown format.

		Raises:
			ValueError: If the URL format is invalid.
			Exception: If the document cannot be fetched or exported.

		"""
		doc_id = extract_doc_id_from_url(doc_url)

		drive_service: Any = self.auth_service.get_drive_service()

		try:
			html_content = (
				drive_service.files()
				.export(fileId=doc_id, mimeType="text/html")
				.execute()
			)
		except Exception as e:
			log_and_raise(
				logger,
				"Failed to export Google Doc as HTML. "
				"Check document permissions and ID.",
				Exception,
				e,
			)

		converter = html2text.HTML2Text()
		converter.ignore_links = True
		converter.ignore_images = True
		converter.body_width = 0  # No line wrapping

		if isinstance(html_content, bytes):
			html_content = html_content.decode("utf-8")

		return converter.handle(html_content)
