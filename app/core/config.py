"""Application configuration settings."""

from dotenv import load_dotenv
from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
	"""Application settings.

	Loads settings from environment variables or a .env file. If not found,
	default values are used where specified.
	"""

	# API settings
	API_PREFIX: str = "/api"
	DEBUG: bool = False

	# CORS settings
	ALLOWED_ORIGINS: str = ""

	# Authentication keys
	APP_API_KEY: SecretStr

	# LLM API Keys
	GOOGLE_API_KEY: SecretStr
	OPENAI_API_KEY: SecretStr
	ANTHROPIC_API_KEY: SecretStr

	# Langfuse Configuration
	LANGFUSE_SECRET_KEY: SecretStr
	LANGFUSE_PUBLIC_KEY: SecretStr
	LANGFUSE_HOST: HttpUrl

	# Inngest Configuration
	# INNGEST_BASE_URL is read directly by the inngest SDK from the process
	# environment; it's declared here only so pydantic doesn't reject it as
	# an unrecognized env var. Comment it out (or unset it) in production to
	# use the default Inngest Cloud URL.
	INNGEST_BASE_URL: str | None = None
	INNGEST_DEV: int
	INNGEST_EVENT_KEY: SecretStr
	INNGEST_SIGNING_KEY: SecretStr

	# GitHub App Configuration
	GITHUB_APP_PRIVATE_KEY: SecretStr
	GITHUB_CLIENT_ID: SecretStr
	GITHUB_INSTALLATION_ID: SecretStr
	GITHUB_APP_SIGNED_JWT_TTL: int = 600
	GITHUB_API_GQL_ENDPOINT: HttpUrl = HttpUrl("https://api.github.com/graphql")

	# Redis Configuration
	REDIS_PASSWORD: SecretStr
	REDIS_HOST: str = "redis"
	REDIS_PORT: int = 6379

	# Slack Configuration
	SLACK_BOT_TOKEN: SecretStr
	SLACK_PMS_CONNECTOR_BOT_TOKEN: SecretStr
	SLACK_PMS_CONNECTOR_SIGNING_SECRET: SecretStr

	# Frappe PMS Configuration
	FRAPPE_BASE_URL: HttpUrl
	FRAPPE_API_TOKEN: SecretStr

	# Google Workspace Configuration
	GOOGLE_SERVICE_ACCOUNT_KEY: SecretStr
	GOOGLE_TEMPLATE_DOC_ID: str
	GOOGLE_SCOPES: str = Field(
		default="https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/documents",
		description="Comma-separated list of Google API scopes",
	)

	@classmethod
	@field_validator("ALLOWED_ORIGINS")
	def parse_allowed_origins(cls, v: str) -> list[str]:
		"""Parse comma-separated origins into a list."""
		return v.split(",") if v else []

	@property
	def google_scopes_list(self) -> list[str]:
		"""Get Google scopes as a list.

		Raises:
			ValueError: If no valid scopes are configured.

		"""
		scopes = [s.strip() for s in self.GOOGLE_SCOPES.split(",") if s.strip()]
		if not scopes:
			raise ValueError(
				"GOOGLE_SCOPES must contain at least one valid scope",
			)
		return scopes

	@model_validator(mode="after")
	def validate_required_secrets(self):
		"""Ensure required secret settings are provided and not empty."""
		if not self.APP_API_KEY.get_secret_value().strip():
			raise ValueError("APP_API_KEY must be set and cannot be empty")

		if not self.SLACK_BOT_TOKEN.get_secret_value().strip():
			raise ValueError("SLACK_BOT_TOKEN must be set and cannot be empty")

		if not self.SLACK_PMS_CONNECTOR_BOT_TOKEN.get_secret_value().strip():
			raise ValueError(
				"SLACK_PMS_CONNECTOR_BOT_TOKEN must be set and cannot be empty",
			)

		if not self.SLACK_PMS_CONNECTOR_SIGNING_SECRET.get_secret_value().strip():
			raise ValueError(
				"SLACK_PMS_CONNECTOR_SIGNING_SECRET must be set and cannot be empty",
			)

		if not self.FRAPPE_API_TOKEN.get_secret_value().strip():
			raise ValueError("FRAPPE_API_TOKEN must be set and cannot be empty")

		# Validate Google Workspace configuration
		if not self.GOOGLE_SERVICE_ACCOUNT_KEY.get_secret_value().strip():
			raise ValueError(
				"GOOGLE_SERVICE_ACCOUNT_KEY must be set and cannot be empty",
			)

		if not self.GOOGLE_TEMPLATE_DOC_ID.strip():
			raise ValueError(
				"GOOGLE_TEMPLATE_DOC_ID must be set and cannot be empty",
			)

		# Validate GOOGLE_SCOPES at initialization
		if not self.GOOGLE_SCOPES.strip():
			raise ValueError(
				"GOOGLE_SCOPES must be set and cannot be empty",
			)

		# Ensure at least one valid scope exists
		_ = self.google_scopes_list

		return self

	class Config:
		"""Pydantic configuration for environment variable loading."""

		env_file = ".env"
		env_file_encoding = "utf-8"
		case_sensitive = True


# Load environment variables from .env file.
load_dotenv()

# Pylance: BaseSettings loads from environment variables.
settings = Settings()  # type: ignore
