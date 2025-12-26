"""Inngest function for Google Docs generation."""

import logging

import inngest
from pydantic import ValidationError

from app.core.adapters import inngest_client
from app.core.utils import validate
from app.google_docs.dependencies import get_google_docs_service
from app.google_docs.inngest.constants import GOOGLE_DOCS_GENERATION_MAX_RETRY
from app.google_docs.inngest.utils import (
	build_replacements_dict,
	generate_doc_name,
	parse_llm_summary,
)
from app.llm.models.summarization import ProjectMetadata, UserMetadata

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
			- summary_json (str): JSON string from LLM summarization
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
		validate(event_data, dict)

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

		validate(summary_json, str)
		validate(project_data, dict)
		validate(user_data, dict)

		# Parse and validate metadata
		project_metadata = ProjectMetadata.model_validate(project_data)
		user_metadata = UserMetadata.model_validate(user_data)

		# Parse LLM summary JSON
		ctx.logger.info("Parsing LLM summary output")
		if not isinstance(summary_json, str):
			raise TypeError(
				f"Expected summary_json to be str, got {type(summary_json)}",
			)
		summary_data = parse_llm_summary(summary_json)

		# Build replacements dictionary for Google Docs template
		ctx.logger.info("Building replacements dictionary")
		replacements = build_replacements_dict(
			summary_data=summary_data,
			project_metadata=project_metadata,
			user_metadata=user_metadata,
		)

		# Generate document name
		doc_name = generate_doc_name(
			project_name=project_metadata.project_name,
			end_date=project_metadata.end_date,
		)
		ctx.logger.info(f"Generating document: {doc_name}")

		# Get Google Docs service and generate document
		google_docs_service = get_google_docs_service()
		result = await google_docs_service.generate_document(
			replacements=replacements,
			doc_name=doc_name,
		)

		ctx.logger.info(f"Document generated successfully: {result['document_url']}")
		return result

	except ValidationError as e:
		ctx.logger.error(f"Validation error for metadata: {e}")
		raise ValueError(f"Invalid metadata: {e}")
	except KeyError as e:
		ctx.logger.error(f"Missing required field in data: {e}")
		raise ValueError(f"Missing required field: {e}")
	except Exception as e:
		ctx.logger.error(f"Error generating Google Doc: {e}")
		raise
