"""Schema for LLM-generated /pms audit tips."""

from pydantic import BaseModel, ConfigDict, Field


class AuditTipsSchema(BaseModel):
	"""Business-value-framed tips for each /pms audit section.

	Each field is null when that section has nothing worth calling out
	(empty or fully healthy) -- the LLM is instructed to say so explicitly
	rather than inventing a tip.
	"""

	model_config = ConfigDict(populate_by_name=True)

	milestones_tip: str | None = Field(default=None, alias="milestonesTip")
	todos_tip: str | None = Field(default=None, alias="todosTip")
	risks_tip: str | None = Field(default=None, alias="risksTip")
	github_tip: str | None = Field(default=None, alias="githubTip")
