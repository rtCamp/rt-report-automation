"""Schemas for LLM-based summarization requests and responses."""

import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.google_docs.utils.helpers import extract_folder_id_from_drive_link
from app.llm.models import LLMProvider, SupportedModels


class ProjectStatus(str, Enum):
	"""Enumeration of project statuses."""

	GREEN = "Green"
	YELLOW = "Yellow"
	RED = "Red"


class ProjectMetadata(BaseModel):
	"""Project metadata schema."""

	start_date: datetime.date = Field(
		description="Start date of the report",
		examples=["2025-08-25"],
	)

	end_date: datetime.date = Field(
		description="End date of the report",
		examples=["2025-09-03"],
	)

	project_status: ProjectStatus = Field(
		description="Status of the project",
		examples=[ProjectStatus.GREEN],
	)

	project_name: str = Field(
		description="Name of the project",
		examples=["AI-Internal"],
		min_length=3,
		max_length=128,
	)

	drive_link: str = Field(
		description="Google Drive folder link where reports should be generated",
		examples=[
			"https://drive.google.com/drive/folders/1iwxHw-G4am1lliSoftEZjzmIxV38P__4"
		],
		min_length=8,
	)

	@field_validator("drive_link")
	@classmethod
	def validate_drive_link(cls, v: str) -> str:
		"""Validate Google Drive link format.

		Args:
			v: The drive link to validate.

		Returns:
			The validated drive link.

		Raises:
			ValueError: If the drive link format is invalid.

		"""
		# Validate format using extraction function
		extract_folder_id_from_drive_link(v)
		return v


class UserMetadata(BaseModel):
	"""User metadata schema."""

	user_name: str = Field(
		description="Name of the user",
		examples=["anonymous"],
		min_length=3,
		max_length=128,
	)

	user_email: EmailStr = Field(
		description="Email of the user",
		examples=["anonymous@anonymous.com"],
	)


class GitHubMetadata(BaseModel):
	"""GitHub repository metadata schema."""

	repo_name: str = Field(
		description="Name of the GitHub repository",
		examples=["AI-Internal"],
		min_length=3,
		max_length=128,
	)

	owner_name: str = Field(
		description="Name of the GitHub repository owner/organization",
		examples=["rtCamp"],
		default="rtCamp",
		min_length=3,
		max_length=128,
	)

	project_board: str = Field(
		description="Name of the project board",
		examples=["AI-Internal"],
		min_length=3,
		max_length=128,
	)


class SlackMetadata(BaseModel):
	"""Slack workspace metadata schema."""

	channel_slug: str = Field(
		description="Slack channel slug",
		examples=["ai"],
		min_length=2,
		max_length=128,
	)


class ModelMetadata(BaseModel):
	"""LLM model metadata schema."""

	provider: LLMProvider = Field(
		description="LLM Provider",
		examples=[LLMProvider.GOOGLE_GENAI],
		default=LLMProvider.GOOGLE_GENAI,
	)

	model: SupportedModels = Field(
		description="Name of the LLM model",
		examples=[SupportedModels.GEMINI_2_5_FLASH],
		default=SupportedModels.GEMINI_2_5_FLASH,
	)

	temperature: float = Field(
		description="Sampling temperature to use, between 0 and 1",
		ge=0,
		le=1,
		examples=[0.7],
		default=0.7,
	)


class SummarizeRequest(BaseModel):
	"""Request schema for LLM-based summarization."""

	request_id: str | None = Field(
		description="Client-generated request ID for websocket updates",
		examples=["f37af14e-8d0f-4aa4-a6b2-a4f7a7250be9"],
		default=None,
	)
	llm_model_overrides: ModelMetadata
	project_metadata: ProjectMetadata
	user_metadata: UserMetadata
	github_metadata: GitHubMetadata
	slack_metadata: SlackMetadata


class SummarizeResponse(BaseModel):
	"""Response schema for LLM-based summarization."""

	request_id: str = Field(
		description="Client correlation ID used for websocket updates",
		examples=["f37af14e-8d0f-4aa4-a6b2-a4f7a7250be9"],
	)
	run_ids: list[str] = Field(
		description="Unique identifier for the summarization run",
		examples=[["123e4567-e89b-12d3-a456"]],
	)


class TaskDetails(BaseModel):
	"""Task details schema."""

	model_config = ConfigDict(populate_by_name=True)

	completed: str
	in_progress: str = Field(alias="inProgress")
	in_review: str = Field(alias="inReview")


class ProjectSummarySchema(BaseModel):
	"""Project summary schema."""

	model_config = ConfigDict(populate_by_name=True)

	summary: str
	risk_blocker_action_needed: str = Field(alias="riskBlockerActionNeeded")
	task_details: TaskDetails = Field(alias="taskDetails")
