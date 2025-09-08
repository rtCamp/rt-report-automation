from dotenv import load_dotenv
from pydantic import HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
	"""
	Application settings.

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
	LANGFUSE_HOST: HttpUrl = HttpUrl("https://cloud.langfuse.com")

	# Inngest Configuration
	INNGEST_BASE_URL: HttpUrl
	INNGEST_DEV: int
	INNGEST_EVENT_KEY: SecretStr
	INNGEST_SIGNING_KEY: SecretStr

	# GitHub App Configuration
	GITHUB_APP_PRIVATE_KEY: SecretStr
	GITHUB_CLIENT_ID: SecretStr
	GITHUB_INSTALLATION_ID: SecretStr
	GITHUB_INSTALLATION_TOKEN_TTL: int = 600
	GITHUB_API_GQL_ENDPOINT: HttpUrl = HttpUrl("https://api.github.com/graphql")

	# Redis Configuration
	REDIS_PASSWORD: SecretStr
	REDIS_CLIENT_HOST: str = "redis"

	@classmethod
	@field_validator("ALLOWED_ORIGINS")
	def parse_allowed_origins(cls, v: str) -> list[str]:
		return v.split(",") if v else []

	@model_validator(mode="after")
	def validate_app_api_key(self):
		if not self.APP_API_KEY.get_secret_value().strip():
			raise ValueError("APP_API_KEY must be set and cannot be empty")
		return self

	class Config:
		env_file = ".env"
		env_file_encoding = "utf-8"
		case_sensitive = True


# Load environment variables from .env file.
load_dotenv()

# Pylance: BaseSettings loads from environment variables.
settings = Settings()  # type: ignore
