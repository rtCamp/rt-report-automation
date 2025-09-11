from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.adapters import setup_inngest
from app.core.api import register_routes
from app.core.config import settings
from app.core.logger import LogLevels, configure_logging
from app.llm.inngest import summarization, summarization_workflow
from app.slack.inngest.slack import fetch_slack

configure_logging(log_level=LogLevels.info)

app = FastAPI(
	title="rt Report Automation",
	description="API for rt Report Automation",
	version="0.1.0",
	docs_url="/docs",
	redoc_url="/redoc",
)

app.add_middleware(
	CORSMiddleware,
	allow_origins=settings.ALLOWED_ORIGINS,
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)

# Register API routes.
register_routes(app)

# Initialize Inngest.
setup_inngest(app, [summarization_workflow, summarization, fetch_slack])

if __name__ == "__main__":
	import uvicorn

	uvicorn.run(
		app="app.main:app",
		host="0.0.0.0",
		port=8000,
		reload=True,
	)
