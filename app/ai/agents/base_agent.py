"""
Base Agent Module

Abstract base class for all AI agents in the SDD platform.
Provides common functionality: LLM initialization, retry logic,
token counting, confidence scoring, error handling, and observability.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from pydantic import BaseModel, ValidationError
from tenacity import (
    AsyncRetrying,
    RetryError,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.ai.config import AIConfig, ModelConfig
from app.ai.utils.confidence_scorer import ConfidenceScorer
from app.ai.utils.token_counter import TokenCounter

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

TOutput = TypeVar("TOutput", bound=BaseModel)


class AgentExecutionError(Exception):
    """Raised when agent execution fails after all retries."""

    def __init__(self, message: str, agent_name: str, attempts: int, original_error: Exception):
        super().__init__(message)
        self.agent_name = agent_name
        self.attempts = attempts
        self.original_error = original_error


class AgentResult(BaseModel):
    """Standard result wrapper for all agent outputs."""

    agent_name: str
    run_id: str
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    confidence_scores: Dict[str, float] = {}
    overall_confidence: float = 0.0
    tokens_used: int = 0
    latency_ms: float = 0.0
    model_used: str = ""
    metadata: Dict[str, Any] = {}


class BaseAgent(ABC, Generic[TOutput]):
    """
    Abstract base class for all SDD AI agents.

    Provides:
    - LLM initialization with GPT-4o
    - Structured output parsing with Pydantic validation
    - Exponential backoff retry logic
    - Token counting and optimization
    - Confidence scoring integration
    - OpenTelemetry distributed tracing
    - Comprehensive error handling and logging
    - RAG context injection
    """

    def __init__(
        self,
        task_name: str,
        output_schema: Type[TOutput],
        model_config: Optional[ModelConfig] = None,
        enable_rag: bool = True,
    ):
        self.task_name = task_name
        self.output_schema = output_schema
        self.enable_rag = enable_rag
        self.agent_name = self.__class__.__name__

        # Get model config for this task
        self.model_config = model_config or AIConfig.get_model_config(task_name)

        # Initialize LLM
        self.llm = self._init_llm()

        # Initialize utilities
        self.token_counter = TokenCounter(model_name=self.model_config.model_name)
        self.confidence_scorer = ConfidenceScorer()
        self.output_parser = JsonOutputParser(pydantic_object=output_schema)

        logger.info(
            "Initialized agent %s with model %s",
            self.agent_name,
            self.model_config.model_name,
        )

    def _init_llm(self) -> ChatOpenAI:
        """Initialize ChatOpenAI pointed at DeepInfra's OpenAI-compatible endpoint."""
        return ChatOpenAI(
            model=self.model_config.model_name,
            temperature=self.model_config.temperature,
            max_tokens=self.model_config.max_tokens,
            api_key=AIConfig.DEEPINFRA_API_KEY,
            base_url=AIConfig.DEEPINFRA_BASE_URL,
            timeout=self.model_config.timeout,
            max_retries=0,  # retries are handled by tenacity
        )

    @abstractmethod
    def get_prompt_template(self) -> ChatPromptTemplate:
        """Return the prompt template for this agent."""
        ...

    @abstractmethod
    async def _parse_output(self, raw_output: str) -> TOutput:
        """Parse and validate the raw LLM output."""
        ...

    def _build_system_message(self) -> str:
        """Build the base system message. Override in subclasses."""
        return (
            "You are an expert software architect and business analyst working on an "
            "enterprise Spec Driven Development platform. Your responses must be precise, "
            "structured, and actionable. Always respond with valid JSON matching the "
            "requested schema exactly."
        )

    def _inject_rag_context(
        self,
        prompt_vars: Dict[str, Any],
        rag_results: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """Inject RAG retrieval context into prompt variables."""
        if not rag_results:
            prompt_vars["rag_context"] = ""
            return prompt_vars

        context_parts = []
        for i, result in enumerate(rag_results[:5], 1):
            context_parts.append(
                f"[Reference {i}] (similarity: {result.get('score', 0):.2f})\n"
                f"{result.get('content', '')}"
            )

        prompt_vars["rag_context"] = (
            "## Relevant Context from Previous Documents\n\n"
            + "\n\n---\n\n".join(context_parts)
            if context_parts
            else ""
        )
        return prompt_vars

    async def _execute_with_retry(
        self,
        prompt_vars: Dict[str, Any],
        config: Optional[RunnableConfig] = None,
    ) -> tuple[str, int]:
        """Execute LLM call with exponential backoff retry logic."""
        prompt_template = self.get_prompt_template()
        chain = prompt_template | self.llm

        last_error: Optional[Exception] = None
        total_tokens = 0

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.model_config.max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            retry=retry_if_exception_type(
                (
                    Exception,  # Broad catch; specific exceptions narrowed below
                )
            ),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=False,
        ):
            with attempt:
                try:
                    logger.debug(
                        "Agent %s: attempt %d/%d",
                        self.agent_name,
                        attempt.retry_state.attempt_number,
                        self.model_config.max_retries,
                    )

                    response: AIMessage = await chain.ainvoke(
                        prompt_vars,
                        config=config,
                    )

                    raw_content = response.content
                    if not isinstance(raw_content, str):
                        raw_content = str(raw_content)

                    # Count tokens from usage metadata if available
                    if hasattr(response, "usage_metadata") and response.usage_metadata:
                        total_tokens = response.usage_metadata.get("total_tokens", 0)
                    else:
                        total_tokens = self.token_counter.count_tokens(raw_content)

                    return raw_content, total_tokens

                except ValidationError as e:
                    last_error = e
                    logger.warning("Agent %s: validation error: %s", self.agent_name, e)
                    raise
                except Exception as e:
                    last_error = e
                    logger.warning(
                        "Agent %s: execution error (attempt %d): %s",
                        self.agent_name,
                        attempt.retry_state.attempt_number,
                        str(e),
                    )
                    raise

        raise AgentExecutionError(
            f"Agent {self.agent_name} failed after {self.model_config.max_retries} attempts",
            agent_name=self.agent_name,
            attempts=self.model_config.max_retries,
            original_error=last_error or RuntimeError("Unknown error"),
        )

    async def run(
        self,
        input_data: Dict[str, Any],
        rag_results: Optional[List[Dict]] = None,
        config: Optional[RunnableConfig] = None,
        organization_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Execute the agent with full observability and error handling.

        Args:
            input_data: Input variables for the prompt template
            rag_results: Optional RAG retrieval results for context
            config: Optional LangChain runnable config (for tracing)
            organization_id: Organization ID for multi-tenant logging

        Returns:
            AgentResult with output data, confidence scores, and metadata
        """
        run_id = str(uuid.uuid4())
        start_time = time.monotonic()

        with tracer.start_as_current_span(
            f"agent.{self.agent_name}",
            kind=SpanKind.INTERNAL,
            attributes={
                "agent.name": self.agent_name,
                "agent.task": self.task_name,
                "agent.run_id": run_id,
                "agent.model": self.model_config.model_name,
                "organization.id": organization_id or "unknown",
            },
        ) as span:
            try:
                logger.info(
                    "Agent %s: starting run %s",
                    self.agent_name,
                    run_id,
                )

                # Inject RAG context
                prompt_vars = self._inject_rag_context(
                    dict(input_data),
                    rag_results,
                )

                # Execute with retry
                raw_output, tokens_used = await self._execute_with_retry(
                    prompt_vars=prompt_vars,
                    config=config,
                )

                span.set_attribute("agent.tokens_used", tokens_used)

                # Parse output
                parsed_output = await self._parse_output(raw_output)

                # Score confidence
                raw_confidence = await self.confidence_scorer.score(
                    task_name=self.task_name,
                    output=parsed_output,
                    input_data=input_data,
                )
                # Keep only float values — ConfidenceBreakdown also returns
                # 'issues' (List[str]) and 'suggestions' (List[str]) which
                # would fail AgentResult's Dict[str, float] validation.
                confidence_scores = {
                    k: v for k, v in raw_confidence.items() if isinstance(v, (int, float))
                }
                overall_confidence = confidence_scores.get("overall", 0.0)

                span.set_attribute("agent.confidence", overall_confidence)
                span.set_attribute("agent.success", True)

                latency_ms = (time.monotonic() - start_time) * 1000

                logger.info(
                    "Agent %s: completed run %s in %.0fms, confidence=%.2f, tokens=%d",
                    self.agent_name,
                    run_id,
                    latency_ms,
                    overall_confidence,
                    tokens_used,
                )

                return AgentResult(
                    agent_name=self.agent_name,
                    run_id=run_id,
                    success=True,
                    data=parsed_output,
                    confidence_scores=confidence_scores,
                    overall_confidence=overall_confidence,
                    tokens_used=tokens_used,
                    latency_ms=latency_ms,
                    model_used=self.model_config.model_name,
                    metadata={
                        "task_name": self.task_name,
                        "organization_id": organization_id,
                    },
                )

            except AgentExecutionError as e:
                span.set_attribute("agent.success", False)
                span.set_attribute("agent.error", str(e))
                span.record_exception(e)
                latency_ms = (time.monotonic() - start_time) * 1000

                logger.error(
                    "Agent %s: failed run %s after %d attempts: %s",
                    self.agent_name,
                    run_id,
                    e.attempts,
                    str(e.original_error),
                )

                return AgentResult(
                    agent_name=self.agent_name,
                    run_id=run_id,
                    success=False,
                    error=str(e),
                    tokens_used=0,
                    latency_ms=latency_ms,
                    model_used=self.model_config.model_name,
                )

            except Exception as e:
                span.set_attribute("agent.success", False)
                span.record_exception(e)
                latency_ms = (time.monotonic() - start_time) * 1000

                logger.exception(
                    "Agent %s: unexpected error in run %s: %s",
                    self.agent_name,
                    run_id,
                    str(e),
                )

                return AgentResult(
                    agent_name=self.agent_name,
                    run_id=run_id,
                    success=False,
                    error=f"Unexpected error: {str(e)}",
                    tokens_used=0,
                    latency_ms=latency_ms,
                    model_used=self.model_config.model_name,
                )

    def _extract_json_from_response(self, raw: str) -> str:
        """Extract JSON from a response that may have markdown code blocks."""
        raw = raw.strip()

        # Handle markdown code blocks
        if "```json" in raw:
            start = raw.find("```json") + 7
            end = raw.rfind("```")
            if end > start:
                return raw[start:end].strip()

        if "```" in raw:
            start = raw.find("```") + 3
            end = raw.rfind("```")
            if end > start:
                return raw[start:end].strip()

        # Find first { or [ and last } or ]
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start_idx = raw.find(start_char)
            end_idx = raw.rfind(end_char)
            if start_idx != -1 and end_idx > start_idx:
                return raw[start_idx : end_idx + 1]

        return raw
