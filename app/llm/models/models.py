from enum import Enum


class LLMProvider(str, Enum):
	OPENAI = "openai"
	GOOGLE_GENAI = "google_genai"
	ANTHROPIC = "anthropic"


class SupportedModels(str, Enum):
	# OpenAI models
	GPT_5 = "gpt-5"
	GPT_4_O = "gpt-4o"
	GPT_4_O_MINI = "gpt-4o-mini"
	GPT_4 = "gpt-4"
	GPT_3_5_TURBO = "gpt-3.5-turbo"

	# Gemini models
	GEMINI_2_5_FLASH = "gemini-2.5-flash"
	GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"
	GEMINI_2_5_PRO = "gemini-2.5-pro"
	GEMINI_2_0_FLASH = "gemini-2.0-flash"
	GEMINI_2_0_FLASH_LITE = "gemini-2.0-flash-lite"

	# Anthropic models
	CLAUDE_3_OPUS = "claude-3-opus-20240229"
	CLAUDE_3_7_SONNET = "claude-3-7-sonnet-20250219"
	CLAUDE_3_HAIKU = "claude-3-haiku-20240307"
