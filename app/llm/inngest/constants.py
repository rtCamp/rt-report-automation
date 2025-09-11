# Maximum allowed tokens for direct summarization without map-reduce.
MAX_ALLOWED_TOKENS = 100_000

# Lower bound for API rate limiting (RPM) for third-party LLM providers.
MIN_PROVIDER_API_RATE_LIMIT = 500

# Text chunk size for `RecursiveCharacterTextSplitter`
CHUNK_SIZE = 16_000

# Text chunk overlap for `RecursiveCharacterTextSplitter`
CHUNK_OVERLAP = 200
