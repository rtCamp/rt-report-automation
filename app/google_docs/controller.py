"""FastAPI controller for Google Docs operations."""

import logging

from fastapi import APIRouter, Depends, status

from app.core.utils import log_and_raise
from app.google_docs.dependencies import get_google_docs_service
from app.google_docs.models.models import GenerateDocRequest, GenerateDocResponse
from app.google_docs.services.google_docs import GoogleDocsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/google-docs", tags=["Google Docs"])


@router.post(
	"/generate",
	summary="Generate Google Doc from template",
	description="""
	Generate a Google Doc by copying a template and replacing
	merge tags with provided content.
	""",
	response_model=GenerateDocResponse,
	status_code=status.HTTP_201_CREATED,
	responses={
		201: {
			"description": "Document generated successfully",
			"content": {
				"application/json": {
					"example": {
						"document_url": "https://docs.google.com/document/d/1234567890abcdef/edit",
					},
				},
			},
		},
		400: {
			"description": "Bad Request - Invalid input",
			"content": {
				"application/json": {
					"example": {
						"detail": "Missing or invalid replacements object",
					},
				},
			},
		},
		500: {
			"description": "Internal Server Error - Document generation failed",
			"content": {
				"application/json": {
					"example": {
						"detail": "Error generating document: Failed to copy template",
					},
				},
			},
		},
	},
)
async def generate_document(
	request: GenerateDocRequest,
	service: GoogleDocsService = Depends(get_google_docs_service),
) -> GenerateDocResponse:
	"""Generate a Google Doc from template with replacements.

	Args:
		request: Document generation request containing replacements and
			optional doc name.
		service: GoogleDocsService instance (injected dependency).

	Returns:
		GenerateDocResponse: Response containing the generated document URL.

	Raises:
		HTTPException:
			- 400 (Bad Request): If replacements is None, not a dict, has empty keys,
				or doc_name is empty.
			- 500 (Internal Server Error): If document creation or update fails due to
				Google API errors, authentication issues, or other unexpected errors.

	"""
	try:
		result = await service.generate_document(
			replacements=request.replacements,
			doc_name=request.doc_name,
		)

		return GenerateDocResponse(**result)

	except ValueError as e:
		log_and_raise(
			logger,
			str(e),
			http_status_code=status.HTTP_400_BAD_REQUEST,
			cause=e,
		)
	except Exception as e:
		log_and_raise(
			logger,
			f"Error generating document: {e}",
			http_status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			cause=e,
		)
