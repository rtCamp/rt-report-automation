"""Pydantic models for Google Docs API."""

from pydantic import BaseModel, Field


class GenerateDocRequest(BaseModel):
	"""Request model for generating a Google Doc.

	Attributes:
		replacements: Dictionary of template tag replacements.
			Keys should match the tags in your template (without delimiters).
			Values can be strings or lists of strings.
		doc_name: Optional custom name for the generated document.

	"""

	replacements: dict[str, str | list[str]] = Field(
		...,
		description="Dictionary of template tag replacements",
		examples=[
			{
				"projectName": "RT Report Automation",
				"from": "December 1, 2025",
				"to": "December 24, 2025",
				"name": "John Doe",
				"projectStatus": "Green",
				"summary": "Project summary text",
				"riskBlockerActionNeeded": "No blockers",
				"completed": "Task 1\nTask 2",
				"inProgress": "Task 3",
				"inReview": "Task 4",
			},
		],
	)

	doc_name: str | None = Field(
		None,
		description="Optional name for the generated document",
		min_length=1,
		max_length=200,
		examples=["Weekly Report - 2025-12-24"],
	)


class GenerateDocResponse(BaseModel):
	"""Response model for document generation.

	Attributes:
		document_url: The URL of the generated Google Doc.

	"""

	document_url: str = Field(
		...,
		description="URL of the generated Google Doc",
		examples=["https://docs.google.com/document/d/1234567890abcdef/edit"],
	)
