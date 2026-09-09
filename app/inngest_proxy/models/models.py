"""Response models for the Inngest run-status proxy."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# Imported at runtime, not only for typing: Pydantic needs the concrete enum
# to validate and to emit it in the OpenAPI schema.
from app.inngest_proxy.errors import RunErrorCode  # noqa: TC001


class RunState(StrEnum):
	"""Coarse run state the frontend renders, derived from the Inngest status."""

	PENDING = "pending"
	RUNNING = "running"
	COMPLETED = "completed"
	FAILED = "failed"
	CANCELLED = "cancelled"


class RunErrorDetail(BaseModel):
	"""Structured failure detail for a terminal, unsuccessful run."""

	error_code: RunErrorCode = Field(
		description="Stable machine-readable code for this failure class.",
	)
	user_message: str = Field(
		description="Plain-language explanation safe to show in a toast.",
	)
	action: str | None = Field(
		default=None,
		description="Suggested next step, when the cause is user-fixable.",
	)
	is_user_fixable: bool = Field(
		description="True when the user can resolve this without engineering.",
	)
	technical_detail: str | None = Field(
		default=None,
		description="Raw failure text from Inngest, truncated. For engineering.",
	)
	resource_url: str | None = Field(
		default=None,
		description=(
			"Link to the specific resource the user must fix (e.g. the Google "
			"Drive folder that needs an 'Automated Docs' subfolder)."
		),
	)
	trace_id: str = Field(
		description="Copyable identifier engineering can use to find the logs.",
	)
	occurred_at: str | None = Field(
		default=None,
		description="ISO-8601 timestamp of when the run reached its failed state.",
	)


class RunStatusResponse(BaseModel):
	"""Normalized run status for the report-generation frontend."""

	event_id: str = Field(description="The Inngest event ID that was polled.")
	run_id: str | None = Field(
		default=None,
		description="The Inngest run ID, absent until a run has been created.",
	)
	state: RunState = Field(description="Coarse run state to render.")
	status: str | None = Field(
		default=None,
		description="Raw Inngest status string, for debugging.",
	)
	is_terminal: bool = Field(
		description="True when polling should stop -- no further state change.",
	)
	message: str = Field(description="Human-readable status line for the toast.")
	document_url: str | None = Field(
		default=None,
		description="URL of the generated report, present only on success.",
	)
	error: RunErrorDetail | None = Field(
		default=None,
		description="Failure detail, present only for failed or cancelled runs.",
	)
	started_at: str | None = Field(
		default=None,
		description="ISO-8601 timestamp of when the run started.",
	)
	ended_at: str | None = Field(
		default=None,
		description="ISO-8601 timestamp of when the run ended.",
	)
	raw: dict[str, Any] | None = Field(
		default=None,
		description="The unmodified Inngest run record, for debugging.",
	)
