from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langfuse import observe
from langfuse.langchain import CallbackHandler

handler = CallbackHandler()
config: RunnableConfig = {
	"callbacks": [handler],
}


@observe(name="llm_invoke_call")
def traced_llm_invoke(
	llm: BaseChatModel,
	input_data: str | list[BaseMessage],
	**kwargs: Any,
) -> Any:
	"""Wrapper for synchronous LLM calls with Langfuse tracing."""
	return llm.invoke(input_data, config=config, **kwargs)


@observe(name="llm_ainvoke_call")
async def traced_llm_ainvoke(
	llm: BaseChatModel,
	input_data: str | list[BaseMessage],
	**kwargs: Any,
) -> Any:
	"""Wrapper for asynchronous LLM calls with Langfuse tracing."""
	return await llm.ainvoke(input_data, config=config, **kwargs)


@observe(name="llm_chain_invoke")
async def traced_chain_ainvoke(
	chain: Any,
	input_data: dict[str, Any],
	**kwargs: Any,
) -> Any:
	"""Wrapper for LangChain chain calls with Langfuse tracing."""
	return await chain.ainvoke(input_data, config=config, **kwargs)
