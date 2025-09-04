from dotenv import load_dotenv
from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
	"""
	Application settings.

	Loads settings from environment variables or a .env file.
	"""

	# API settings
	API_PREFIX: str = "/api"
	DEBUG: bool = False

	# CORS settings
	ALLOWED_ORIGINS: str = ""

	# Authentication keys
	APP_API_KEY: SecretStr = SecretStr("")

	# LLM API Keys
	GOOGLE_API_KEY: SecretStr = SecretStr("")
	OPENAI_API_KEY: SecretStr = SecretStr("")
	ANTHROPIC_API_KEY: SecretStr = SecretStr("")

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
settings = Settings()
