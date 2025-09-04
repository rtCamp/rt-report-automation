import datetime
from enum import Enum

from pydantic import BaseModel, EmailStr, Field

from app.llm.models import LLMProvider, SupportedModels


class ProjectStatus(str, Enum):
	GREEN = "Green"
	YELLOW = "Yellow"
	RED = "Red"


class ProjectMetadata(BaseModel):
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
		examples=["AI Internal"],
		min_length=3,
		max_length=128,
	)


class UserMetadata(BaseModel):
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
	repo_name: str = Field(
		description="Name of the GitHub repository",
		examples=["rt-report-automation"],
		min_length=3,
		max_length=128,
	)

	project_board: str = Field(
		description="Name of the project board",
		examples=["AI Internal"],
		min_length=3,
		max_length=128,
	)


class SlackMetadata(BaseModel):
	channel_slug: str = Field(
		description="Slack channel slug",
		examples=["#general"],
		min_length=2,
		max_length=128,
	)


class ModelMetadata(BaseModel):
	provider: LLMProvider = Field(
		description="LLM Provider",
		examples=[LLMProvider.GOOGLE_GENAI],
		default=LLMProvider.GOOGLE_GENAI,
	)

	model_name: SupportedModels = Field(
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
	llm_model_overrides: ModelMetadata
	project_metadata: ProjectMetadata
	user_metadata: UserMetadata
	github_metadata: GitHubMetadata
	slack_metadata: SlackMetadata


class SummarizeResponse(BaseModel):
	run_id: str = Field(
		description="Unique identifier for the summarization run",
		examples=["123e4567-e89b-12d3-a456"],
	)
