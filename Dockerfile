FROM python:3.14-slim

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy the application into the container.
COPY . /app

# Install the application dependencies.
WORKDIR /app
RUN uv sync --frozen --no-cache

# Install pip (absent from uv venvs by default) then download the spaCy model
# required by the PII anonymizer.
RUN uv pip install pip && uv run python -m spacy download en_core_web_lg

# Expose the application port.
EXPOSE 8000

# Run the application.
CMD ["uv", "run", "-m", "app.main"]
