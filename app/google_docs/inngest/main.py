"""Inngest function for Google Docs generation."""

import logging

import inngest
from pydantic import ValidationError

from app.core.adapters import inngest_client
from app.core.utils import log_and_raise
from app.google_docs.dependencies import get_google_docs_service
from app.google_docs.inngest.constants import GOOGLE_DOCS_GENERATION_MAX_RETRY
from app.google_docs.inngest.utils import (
	build_replacements_dict,
	generate_doc_name,
)
from app.llm.models.summarization import (
	ProjectMetadata,
	ProjectSummarySchema,
	UserMetadata,
)

logger = logging.getLogger(__name__)


@inngest_client.create_function(
	fn_id="generate_google_doc",
	trigger=inngest.TriggerEvent(event="rt-report-automation/generate_google_doc"),
	retries=GOOGLE_DOCS_GENERATION_MAX_RETRY,
)
async def generate_google_doc(ctx: inngest.Context) -> dict[str, str]:
	"""Inngest function to generate Google Doc from LLM summary.

	This function receives the summary from the LLM summarization step,
	transforms it into the format expected by the Google Docs template,
	and generates a document.

	Args:
		ctx (inngest.Context): The Inngest context containing event.data with:
			- summary_json (str | dict): LLM summary (Inngest auto-deserializes JSON)
			- project_metadata (dict): Project metadata (name, dates, status)
			- user_metadata (dict): User metadata (name, email)

	Returns:
		dict[str, str]: Dictionary containing the document URL.
			Example: {"document_url": "https://docs.google.com/document/d/..."}

	Raises:
		TypeError: If event data or metadata types don't match expected types.
		ValueError: If validation fails for metadata or required fields are missing.
		json.JSONDecodeError: If summary JSON is invalid.
		Exception: For any other errors during document generation.

	"""
	try:
		event_data = ctx.event.data

		# Extract and validate required fields
		summary_json = event_data.get("summary_json")
		project_data = event_data.get("project_metadata")
		user_data = event_data.get("user_metadata")

		if not summary_json:
			raise ValueError("Missing required field: summary_json")
		if not project_data:
			raise ValueError("Missing required field: project_metadata")
		if not user_data:
			raise ValueError("Missing required field: user_metadata")

		# Parse and validate all data with Pydantic models
		project_metadata = ProjectMetadata.model_validate(project_data)
		user_metadata = UserMetadata.model_validate(user_data)
		summary_metadata = ProjectSummarySchema.model_validate(summary_json)

		# Build replacements dictionary for Google Docs template
		# 'by_alias=True' to convert field names to camelCase
		replacements = build_replacements_dict(
			summary_data=summary_metadata.model_dump(by_alias=True),
			project_metadata=project_metadata,
			user_metadata=user_metadata,
		)

		# Generate document name
		doc_name = generate_doc_name(
			project_name=project_metadata.project_name,
			start_date=project_metadata.start_date,
			end_date=project_metadata.end_date,
		)

		# Get Google Docs service
		google_docs_service = get_google_docs_service()

		# Return generated document URL
		return await google_docs_service.generate_document(
			replacements=replacements,
			doc_name=doc_name,
		)

	except ValidationError as e:
		log_and_raise(
			logger,
			"Validation error for metadata",
			ValueError,
			cause=e,
		)
	except KeyError as e:
		log_and_raise(
			logger,
			"Missing required field in data",
			ValueError,
			cause=e,
		)
	except Exception as e:
		log_and_raise(
			logger,
			"Error generating Google Doc",
			Exception,
			cause=e,
		)
