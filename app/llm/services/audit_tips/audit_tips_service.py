"""Service for generating LLM-based /pms audit tips."""

from langchain_core.language_models import BaseLanguageModel
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from langfuse import observe

from app.core.adapters.langfuse import langfuse, traced_chain_ainvoke
from app.llm.models.audit_tips import AuditTipsSchema
from app.llm.prompts.audit_tips_prompt import AUDIT_TIPS_FORMAT
from app.llm.prompts.prompt import PII_INSTRUCTION


class AuditTipsService:
	"""Service for generating business-value-framed tips for /pms audit."""

	def __init__(
		self,
		llm: BaseLanguageModel,
		audit_data_json: str,
		prompt_slug: str = "pms-audit-tips",
	):
		"""Initialize the AuditTipsService.

		Args:
			llm: The language model to use.
			audit_data_json: The project's milestones/todos/risks/github_issues,
				already JSON-serialized (and anonymized/sanitized by the
				caller). Taken as a string rather than a dict so callers
				that ran it through text-level sanitization (which isn't
				guaranteed to preserve valid JSON syntax) don't need to
				re-parse it -- it's only ever used as prompt text here, so
				it never needs to be valid JSON again after sanitization.
			prompt_slug: The Langfuse prompt registry slug to fetch.

		"""
		self.llm = llm
		self.audit_data_json = audit_data_json
		self.prompt_slug = prompt_slug

	@observe(name="audit_tips_generate")
	async def generate(self) -> str:
		"""Generate audit tips from the project's audit data.

		Returns:
			str: JSON string matching `AuditTipsSchema`.

		"""
		pydantic_parser = PydanticOutputParser(pydantic_object=AuditTipsSchema)

		langfuse_prompt = langfuse.get_prompt(self.prompt_slug)
		prompt_template = langfuse_prompt.get_langchain_prompt(format=AUDIT_TIPS_FORMAT)
		# Ensure PII placeholders are preserved, same as the summarization prompt.
		prompt_template = f"{PII_INSTRUCTION}\n{prompt_template}"

		prompt = PromptTemplate.from_template(prompt_template)
		chain = prompt | self.llm | pydantic_parser

		result = await traced_chain_ainvoke(
			chain,
			{
				"audit_data": self.audit_data_json,
				"format_instructions": pydantic_parser.get_format_instructions(),
			},
		)

		return result.model_dump_json(by_alias=True)
