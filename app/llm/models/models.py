"""LLM models definitions and configurations."""

from enum import Enum

from pydantic import BaseModel

DEFAULT_CONTEXT_WINDOW = 128_000
DEFAULT_MAX_OUTPUT_TOKENS = 8_000


class ModelResponse(BaseModel):
	"""Response model for LLM model details."""

	name: str
	context_window: int
	max_output_tokens: int


class LLMProvider(str, Enum):
	"""Enumeration of supported LLM providers."""

	OPENAI = "openai"
	GOOGLE_GENAI = "google_genai"
	ANTHROPIC = "anthropic"


class SupportedModels(str, Enum):
	"""Enumeration of supported LLM models."""

	# OpenAI models
	GPT_5 = "gpt-5"
	GPT_5_MINI = "gpt-5-mini"
	GPT_5_NANO = "gpt-5-nano"
	GPT_4_1 = "gpt-4.1"
	GPT_4_O = "gpt-4o"
	GPT_4_O_MINI = "gpt-4o-mini"

	# Gemini models
	GEMINI_2_5_PRO = "gemini-2.5-pro"
	GEMINI_2_5_FLASH = "gemini-2.5-flash"
	GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"
	GEMINI_2_0_FLASH = "gemini-2.0-flash"
	GEMINI_2_0_FLASH_LITE = "gemini-2.0-flash-lite"

	# Anthropic models
	CLAUDE_OPUS_4_1 = "claude-opus-4-1-20250805"
	CLAUDE_OPUS_4 = "claude-opus-4-20250514"
	CLAUDE_SONNET_4 = "claude-sonnet-4-20250514"
	CLAUDE_SONNET_3_7 = "claude-3-7-sonnet-20250219"
	CLAUDE_HAIKU_3_5 = "claude-3-5-haiku-20241022"
	CLAUDE_HAIKU_3 = "claude-3-haiku-20240307"

	def get_context_size(self) -> int:
		"""Get the context window size for the model.

		Returns:
			int: Context window size.

		"""
		return _MODEL_CONTEXT_WINDOW_MAP.get(self, DEFAULT_CONTEXT_WINDOW)

	def get_max_output_tokens(self) -> int:
		"""Get the maximum output tokens for the model.

		Returns:
			int: Maximum output tokens.

		"""
		return _MODEL_MAX_OUTPUT_TOKENS_MAP.get(self, DEFAULT_MAX_OUTPUT_TOKENS)


_MODEL_CONTEXT_WINDOW_MAP: dict[SupportedModels, int] = {
	# OpenAI models (see: https://platform.openai.com/docs/models)
	SupportedModels.GPT_5: 400_000,
	SupportedModels.GPT_5_MINI: 400_000,
	SupportedModels.GPT_5_NANO: 400_000,
	SupportedModels.GPT_4_1: 1_047_576,
	SupportedModels.GPT_4_O: 128_000,
	SupportedModels.GPT_4_O_MINI: 128_000,
	# Gemini models (see: https://ai.google.dev/gemini-api/docs/models)
	SupportedModels.GEMINI_2_5_PRO: 1_048_576,
	SupportedModels.GEMINI_2_5_FLASH: 1_048_576,
	SupportedModels.GEMINI_2_5_FLASH_LITE: 1_048_576,
	SupportedModels.GEMINI_2_0_FLASH: 1_048_576,
	SupportedModels.GEMINI_2_0_FLASH_LITE: 1_048_576,
	# Anthropic models (see: https://docs.anthropic.com/en/docs/about-claude/models)
	SupportedModels.CLAUDE_OPUS_4_1: 200_000,
	SupportedModels.CLAUDE_OPUS_4: 200_000,
	SupportedModels.CLAUDE_SONNET_4: 200_000,
	SupportedModels.CLAUDE_SONNET_3_7: 200_000,
	SupportedModels.CLAUDE_HAIKU_3_5: 200_000,
	SupportedModels.CLAUDE_HAIKU_3: 200_000,
}

_MODEL_MAX_OUTPUT_TOKENS_MAP: dict[SupportedModels, int] = {
	# OpenAI models (see: https://platform.openai.com/docs/models)
	SupportedModels.GPT_5: 128_000,
	SupportedModels.GPT_5_MINI: 128_000,
	SupportedModels.GPT_5_NANO: 128_000,
	SupportedModels.GPT_4_1: 32_768,
	SupportedModels.GPT_4_O: 16_384,
	SupportedModels.GPT_4_O_MINI: 16_384,
	# Gemini models (see: https://ai.google.dev/gemini-api/docs/models)
	SupportedModels.GEMINI_2_5_PRO: 65_536,
	SupportedModels.GEMINI_2_5_FLASH: 65_536,
	SupportedModels.GEMINI_2_5_FLASH_LITE: 65_536,
	SupportedModels.GEMINI_2_0_FLASH: 8_192,
	SupportedModels.GEMINI_2_0_FLASH_LITE: 8_192,
	# Anthropic models (see: https://docs.anthropic.com/en/docs/about-claude/models)
	SupportedModels.CLAUDE_OPUS_4_1: 32_000,
	SupportedModels.CLAUDE_OPUS_4: 32_000,
	SupportedModels.CLAUDE_SONNET_4: 64_000,
	SupportedModels.CLAUDE_SONNET_3_7: 64_000,
	SupportedModels.CLAUDE_HAIKU_3_5: 8_192,
	SupportedModels.CLAUDE_HAIKU_3: 4096,
}
