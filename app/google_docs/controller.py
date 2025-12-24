"""FastAPI controller for Google Docs operations."""

import logging

from fastapi import APIRouter, HTTPException, status

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
) -> GenerateDocResponse:
	"""Generate a Google Doc from template with replacements.

	Args:
		request: Document generation request containing replacements and
		optional doc name.

	Returns:
		GenerateDocResponse: Response containing the generated document URL.

	Raises:
		HTTPException: 400 for invalid input, 500 for generation errors.

	"""
	try:
		service = GoogleDocsService()
		result = await service.generate_document(
			replacements=request.replacements,
			doc_name=request.doc_name,
		)

		logger.info(f"Document generated successfully: {result['document_url']}")

		return GenerateDocResponse(**result)

	except ValueError as e:
		logger.error(f"Validation error: {str(e)}")
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail=str(e),
		) from e
	except Exception as e:
		logger.error(f"Error generating document: {str(e)}")
		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail=f"Error generating document: {str(e)}",
		) from e
