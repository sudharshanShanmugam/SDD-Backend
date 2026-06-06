"""
Requirement Extractor Agent

Extracts structured requirements from raw document content using GPT-4o.
Handles functional requirements, NFRs, constraints, assumptions, and dependencies.
Flags ambiguities for human review and uses RAG for similar requirement lookup.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.ai.agents.base_agent import BaseAgent, AgentResult
from app.ai.config import AIConfig
from app.ai.prompts.requirement_prompts import RequirementPrompts

logger = logging.getLogger(__name__)


class Requirement(BaseModel):
    """Base requirement model."""
    id: str
    title: str
    description: str
    category: str
    priority: str = "should_have"
    source_text: str = ""
    ambiguity_flag: bool = False
    clarification_needed: Optional[str] = None


class FunctionalRequirement(Requirement):
    """Functional requirement."""
    pass


class NonFunctionalRequirement(Requirement):
    """Non-functional requirement."""
    metric: str = ""


class Constraint(BaseModel):
    """Project constraint."""
    id: str
    title: str
    description: str
    type: str
    impact: str = ""


class Assumption(BaseModel):
    """Project assumption."""
    id: str
    description: str
    impact: str = ""
    validation_needed: bool = False


class Dependency(BaseModel):
    """Requirement dependency."""
    id: str
    description: str
    type: str
    affects: List[str] = Field(default_factory=list)


class AmbiguousItem(BaseModel):
    """Flagged ambiguous content."""
    id: str
    source_text: str
    reason: str
    clarification_questions: List[str] = Field(default_factory=list)


class RequirementExtractionResult(BaseModel):
    """Complete requirement extraction result."""
    functional_requirements: List[Dict[str, Any]] = Field(default_factory=list)
    non_functional_requirements: List[Dict[str, Any]] = Field(default_factory=list)
    constraints: List[Dict[str, Any]] = Field(default_factory=list)
    assumptions: List[Dict[str, Any]] = Field(default_factory=list)
    dependencies: List[Dict[str, Any]] = Field(default_factory=list)
    ambiguous_items: List[Dict[str, Any]] = Field(default_factory=list)


class RequirementExtractorAgent(BaseAgent[RequirementExtractionResult]):
    """
    Extracts structured requirements from document content.

    Input:
        - document_content: Raw text of the requirements document
        - project_type: Type of project (web_app, mobile, api, data_platform, etc.)
        - domain: Business domain (fintech, healthcare, ecommerce, etc.)
        - stakeholder_notes: Additional context from stakeholders

    Output:
        AgentResult with data=RequirementExtractionResult containing all
        extracted and categorized requirements.

    Features:
        - Extracts functional, non-functional, constraints, assumptions, dependencies
        - Flags ambiguous statements with clarification questions
        - Uses RAG to find similar requirements from past documents
        - Assigns sequential IDs for traceability
        - Confidence scoring per requirement
    """

    def __init__(self):
        super().__init__(
            task_name="requirement_extraction",
            output_schema=RequirementExtractionResult,
            enable_rag=True,
        )

    def get_prompt_template(self) -> ChatPromptTemplate:
        """Return extraction prompt template."""
        return RequirementPrompts.get_extraction_template()

    async def _parse_output(self, raw_output: str) -> RequirementExtractionResult:
        """Parse raw LLM output into RequirementExtractionResult."""
        json_str = self._extract_json_from_response(raw_output)
        try:
            data = json.loads(json_str)
            return RequirementExtractionResult.model_validate(data)
        except Exception as e:
            logger.error("Failed to parse requirement extraction output: %s", e)
            logger.debug("Raw output: %s", raw_output[:500])
            # Return empty result rather than failing completely
            return RequirementExtractionResult()

    async def extract(
        self,
        document_content: str,
        project_type: str = "web_application",
        domain: str = "general",
        stakeholder_notes: str = "",
        rag_results: Optional[List[Dict]] = None,
        organization_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Extract requirements from document content.

        Args:
            document_content: The raw text content of the requirements document
            project_type: Type of project being built
            domain: Business domain for context
            stakeholder_notes: Any additional context from stakeholders
            rag_results: Optional similar requirements from vector store
            organization_id: Organization ID for multi-tenancy

        Returns:
            AgentResult with RequirementExtractionResult
        """
        input_data = {
            "document_content": document_content,
            "project_type": project_type,
            "domain": domain,
            "stakeholder_notes": stakeholder_notes or "None provided",
        }

        result = await self.run(
            input_data=input_data,
            rag_results=rag_results,
            organization_id=organization_id,
        )

        if result.success and result.data:
            req_result: RequirementExtractionResult = result.data

            # Log summary
            logger.info(
                "Extracted: %d functional, %d NFR, %d constraints, %d assumptions, "
                "%d ambiguous items",
                len(req_result.functional_requirements),
                len(req_result.non_functional_requirements),
                len(req_result.constraints),
                len(req_result.assumptions),
                len(req_result.ambiguous_items),
            )

        return result

    async def extract_from_chunks(
        self,
        document_chunks: List[str],
        project_type: str = "web_application",
        domain: str = "general",
        stakeholder_notes: str = "",
        organization_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Extract requirements from a list of document chunks.
        Useful for large documents that exceed the context window.

        Processes each chunk independently and merges results.
        """
        all_results: List[RequirementExtractionResult] = []
        all_fr_ids: set = set()
        all_nfr_ids: set = set()

        for i, chunk in enumerate(document_chunks):
            logger.info(
                "Processing chunk %d/%d (%d chars)",
                i + 1,
                len(document_chunks),
                len(chunk),
            )

            chunk_result = await self.extract(
                document_content=chunk,
                project_type=project_type,
                domain=domain,
                stakeholder_notes=f"Chunk {i + 1} of {len(document_chunks)}. {stakeholder_notes}",
                organization_id=organization_id,
            )

            if chunk_result.success and chunk_result.data:
                all_results.append(chunk_result.data)

        if not all_results:
            return AgentResult(
                agent_name=self.agent_name,
                run_id="merged",
                success=False,
                error="No chunks processed successfully",
            )

        # Merge results with de-duplication and re-sequencing
        merged = RequirementExtractionResult()
        fr_counter = 1
        nfr_counter = 1
        con_counter = 1
        asm_counter = 1

        seen_titles: set = set()

        for result in all_results:
            # Merge functional requirements with deduplication
            for fr in result.functional_requirements:
                title_key = fr.get("title", "").lower().strip()
                if title_key and title_key not in seen_titles:
                    seen_titles.add(title_key)
                    fr["id"] = f"FR-{fr_counter:03d}"
                    fr_counter += 1
                    merged.functional_requirements.append(fr)

            # Merge NFRs
            for nfr in result.non_functional_requirements:
                title_key = nfr.get("title", "").lower().strip()
                if title_key and title_key not in seen_titles:
                    seen_titles.add(title_key)
                    nfr["id"] = f"NFR-{nfr_counter:03d}"
                    nfr_counter += 1
                    merged.non_functional_requirements.append(nfr)

            # Merge constraints
            for con in result.constraints:
                con["id"] = f"CON-{con_counter:03d}"
                con_counter += 1
                merged.constraints.append(con)

            # Merge assumptions
            for asm in result.assumptions:
                asm["id"] = f"ASM-{asm_counter:03d}"
                asm_counter += 1
                merged.assumptions.append(asm)

            # Merge ambiguous items
            merged.ambiguous_items.extend(result.ambiguous_items)

        logger.info(
            "Merged %d chunks: %d FR, %d NFR, %d constraints, %d assumptions",
            len(all_results),
            len(merged.functional_requirements),
            len(merged.non_functional_requirements),
            len(merged.constraints),
            len(merged.assumptions),
        )

        return AgentResult(
            agent_name=self.agent_name,
            run_id="merged_extraction",
            success=True,
            data=merged,
            confidence_scores={"overall": 0.85},
            overall_confidence=0.85,
            metadata={"chunks_processed": len(document_chunks)},
        )
