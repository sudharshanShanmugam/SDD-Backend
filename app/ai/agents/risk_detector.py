"""
Risk Detector Agent

Analyzes requirements and project context to identify technical, business,
security, and delivery risks with mitigation strategies.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.ai.agents.base_agent import BaseAgent, AgentResult
from app.ai.prompts.system_prompts import SystemPrompts

logger = logging.getLogger(__name__)


RISK_DETECTION_SYSTEM = SystemPrompts.SOFTWARE_ARCHITECT + """

## Risk Detection Framework
Analyze requirements for the following risk categories:

1. **Technical Risks**: Unproven technology, complex integrations, performance bottlenecks
2. **Security Risks**: Authentication/authorization gaps, data exposure, injection vulnerabilities
3. **Business Risks**: Scope creep potential, unclear requirements, stakeholder alignment
4. **Delivery Risks**: Dependencies on third parties, team skill gaps, timeline feasibility
5. **Compliance Risks**: GDPR, HIPAA, SOC2, WCAG requirements
6. **Scalability Risks**: Design decisions that limit future growth
7. **Integration Risks**: External API dependencies, data migration challenges

## Risk Scoring
- Probability: 1-5 (1=rare, 5=almost certain)
- Impact: 1-5 (1=negligible, 5=catastrophic)
- Risk Score = Probability × Impact (1-25)

## Output Schema
{
  "risks": [
    {
      "id": "RISK-XXX",
      "title": "string",
      "category": "technical|security|business|delivery|compliance|scalability|integration",
      "description": "string",
      "affected_items": ["FR-XXX", "EPIC-XXX"],
      "probability": 1,
      "impact": 1,
      "risk_score": 1,
      "severity": "critical|high|medium|low",
      "triggers": ["string (conditions that activate this risk)"],
      "mitigation_strategies": ["string"],
      "contingency_plan": "string",
      "owner_role": "string (who should own this risk)",
      "detection_methods": ["string (how to detect early warning signs)"]
    }
  ],
  "risk_matrix": {
    "critical": ["RISK-XXX"],
    "high": [],
    "medium": [],
    "low": []
  },
  "top_risks": ["RISK-XXX"],
  "risk_summary": {
    "total_risks": 0,
    "critical_count": 0,
    "high_count": 0,
    "medium_count": 0,
    "low_count": 0,
    "overall_risk_level": "string",
    "recommendation": "string"
  }
}"""


class Risk(BaseModel):
    id: str
    title: str
    category: str
    description: str
    affected_items: List[str] = Field(default_factory=list)
    probability: int = 3
    impact: int = 3
    risk_score: int = 9
    severity: str = "medium"
    triggers: List[str] = Field(default_factory=list)
    mitigation_strategies: List[str] = Field(default_factory=list)
    contingency_plan: str = ""
    owner_role: str = ""
    detection_methods: List[str] = Field(default_factory=list)


class RiskDetectionResult(BaseModel):
    risks: List[Dict[str, Any]] = Field(default_factory=list)
    risk_matrix: Dict[str, List[str]] = Field(default_factory=dict)
    top_risks: List[str] = Field(default_factory=list)
    risk_summary: Dict[str, Any] = Field(default_factory=dict)


class RiskDetectorAgent(BaseAgent[RiskDetectionResult]):
    """
    Detects and analyzes risks in requirements and project context.

    Identifies risks across seven categories with quantified
    probability/impact scoring and actionable mitigation strategies.

    Use this agent:
    - After requirement extraction to find requirement-level risks
    - After epic generation to find architectural risks
    - Before sprint planning to flag delivery risks
    """

    def __init__(self):
        super().__init__(
            task_name="risk_detection",
            output_schema=RiskDetectionResult,
            enable_rag=True,
        )
        self._prompt_template: Optional[ChatPromptTemplate] = None

    def get_prompt_template(self) -> ChatPromptTemplate:
        if self._prompt_template is None:
            self._prompt_template = ChatPromptTemplate.from_messages([
                ("system", RISK_DETECTION_SYSTEM),
                ("human", """## Project Context
{project_context}

## Requirements to Analyze
{requirements_json}

## Epics to Analyze
{epics_json}

## Team Context
Team Size: {team_size}
Experience Level: {experience_level}
Timeline: {timeline}

## Regulatory/Compliance Requirements
{compliance_requirements}

{rag_context}

## Instructions
1. Analyze ALL requirements and epics for risks
2. Score each risk with probability (1-5) and impact (1-5)
3. Identify specific triggers and early warning signs
4. Provide concrete, actionable mitigation strategies (not generic advice)
5. Prioritize the top 5 most critical risks
6. Respond ONLY with valid JSON"""),
            ])
        return self._prompt_template

    async def _parse_output(self, raw_output: str) -> RiskDetectionResult:
        json_str = self._extract_json_from_response(raw_output)
        try:
            data = json.loads(json_str)
            return RiskDetectionResult.model_validate(data)
        except Exception as e:
            logger.error("Failed to parse risk detection output: %s", e)
            return RiskDetectionResult()

    async def detect(
        self,
        requirements: List[Dict[str, Any]],
        epics: Optional[List[Dict[str, Any]]] = None,
        project_context: str = "",
        team_size: int = 5,
        experience_level: str = "mid-level",
        timeline: str = "6 months",
        compliance_requirements: Optional[List[str]] = None,
        rag_results: Optional[List[Dict]] = None,
        organization_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Detect risks in requirements and epics.

        Args:
            requirements: Structured requirements to analyze
            epics: Optional epics to analyze for additional risks
            project_context: Project overview and context
            team_size: Number of team members
            experience_level: Team experience level
            timeline: Expected project timeline
            compliance_requirements: Regulatory frameworks to check against
            rag_results: Similar past risk analyses for reference
            organization_id: Organization ID

        Returns:
            AgentResult with RiskDetectionResult
        """
        input_data = {
            "project_context": project_context or "Enterprise SDD Platform",
            "requirements_json": json.dumps(requirements, indent=2),
            "epics_json": json.dumps(epics or [], indent=2),
            "team_size": str(team_size),
            "experience_level": experience_level,
            "timeline": timeline,
            "compliance_requirements": json.dumps(
                compliance_requirements or ["GDPR", "WCAG 2.1 AA"], indent=2
            ),
        }

        result = await self.run(
            input_data=input_data,
            rag_results=rag_results,
            organization_id=organization_id,
        )

        if result.success and result.data:
            risk_result: RiskDetectionResult = result.data
            summary = risk_result.risk_summary
            critical_count = summary.get("critical_count", 0)

            if critical_count > 0:
                logger.warning(
                    "CRITICAL RISKS DETECTED: %d critical risks require immediate attention",
                    critical_count,
                )

            logger.info(
                "Risk detection complete: %d total risks (critical=%d, high=%d)",
                summary.get("total_risks", 0),
                summary.get("critical_count", 0),
                summary.get("high_count", 0),
            )

        return result
