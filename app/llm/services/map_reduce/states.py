import operator
from typing import Annotated, TypedDict

from langchain.schema import Document


class OverallState(TypedDict):
	"""Overall state for map-reduce summarization."""

	contents: list[str]
	summaries: Annotated[list[str], operator.add]
	collapsed_summaries: list[Document]
	final_summary: str


class SummaryState(TypedDict):
	"""State of the node that we will "map" all documents to generate summaries."""

	content: str
