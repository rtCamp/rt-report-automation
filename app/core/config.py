from dotenv import load_dotenv
from pydantic import field_validator
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
	AUTH_SECRET_KEY: str = ""
	AUTH_ALGORITHM: str = "HS256"
	AUTH_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

	# LLM API Keys
	GOOGLE_API_KEY: str = ""
	OPENAI_API_KEY: str = ""
	ANTHROPIC_API_KEY: str = ""

	@classmethod
	@field_validator("ALLOWED_ORIGINS")
	def parse_allowed_origins(cls, v: str) -> list[str]:
		return v.split(",") if v else []

	class Config:
		env_file = ".env"
		env_file_encoding = "utf-8"
		case_sensitive = True


# Load environment variables from .env file.
load_dotenv()
settings = Settings()
