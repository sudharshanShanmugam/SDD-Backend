"""
AI Prompts Package

Contains all prompt templates for the SDD AI agents.
"""

from app.ai.prompts.system_prompts import SystemPrompts
from app.ai.prompts.requirement_prompts import RequirementPrompts
from app.ai.prompts.epic_prompts import EpicPrompts
from app.ai.prompts.story_prompts import StoryPrompts
from app.ai.prompts.sprint_prompts import SprintPrompts
from app.ai.prompts.task_prompts import TaskPrompts
from app.ai.prompts.qa_prompts import QAPrompts
from app.ai.prompts.spec_prompts import SpecPrompts

__all__ = [
    "SystemPrompts",
    "RequirementPrompts",
    "EpicPrompts",
    "StoryPrompts",
    "SprintPrompts",
    "TaskPrompts",
    "QAPrompts",
    "SpecPrompts",
]
