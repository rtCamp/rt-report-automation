"""Inngest function for fetching previous report content."""

import logging

import inngest

from app.core.adapters import inngest_client
from app.google_docs.services.doc_fetcher import DocFetcherService

logger = logging.getLogger(__name__)


@inngest_client.create_function(
	fn_id="fetch_previous_report",
	trigger=inngest.TriggerEvent(
		event="rt-report-automation/fetch_previous_report",
	),
	retries=2,
)
async def fetch_previous_report(ctx: inngest.Context) -> str | None:
	"""Inngest function to fetch previous report content as Markdown.

	Args:
		ctx (inngest.Context): The Inngest context containing event.data with:
			- previous_doc_url (str): Google Docs URL of the previous report.

	Returns:
		str | None: Previous report content in Markdown format,
			or None if no URL is provided.

	Raises:
		Exception: If the document cannot be fetched.

	"""
	previous_doc_url = ctx.event.data.get("previous_doc_url")

	if not previous_doc_url or not isinstance(previous_doc_url, str):
		return None

	doc_fetcher = DocFetcherService()
	return await doc_fetcher.fetch_doc_as_markdown(previous_doc_url)
