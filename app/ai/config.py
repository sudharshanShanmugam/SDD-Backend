"""
AI Configuration Module

Centralised configuration for all AI models, temperatures, token limits,
and other AI-related settings for the SDD platform.

Provider: DeepInfra (OpenAI-compatible endpoint)
  LLM       → LLM_MODEL        (default: openai/gpt-oss-120b-Turbo)
  Embeddings → EMBED_MODEL      (default: BAAI/bge-large-en-v1.5, 1024-dim)
  Fast/NER   → ENTITY_MODEL     (default: meta-llama/Meta-Llama-3.1-8B-Instruct)

Required environment variables:
    DEEPINFRA_API_KEY   - DeepInfra API key
    DEEPINFRA_BASE_URL  - Base URL (default: https://api.deepinfra.com/v1/openai)
    LLM_MODEL           - Main reasoning model
    EMBED_MODEL         - Embedding model
    ENTITY_MODEL        - Fast/entity extraction model

Optional:
    CHROMA_PERSIST_DIR  - ChromaDB persistence directory (default: ./chroma_db)
    REDIS_URL           - Redis URL (default: redis://localhost:6379)
    DATABASE_URL        - PostgreSQL URL for workflow checkpointing
    LANGSMITH_API_KEY   - LangSmith API key (for tracing)
"""

from __future__ import annotations

import os
from copy import copy
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

# Load .env so os.getenv() sees values even outside a FastAPI request context.
# __file__ = backend/app/ai/config.py  →  parents[2] = backend/
try:
    from dotenv import load_dotenv as _load_dotenv
    _env_file = Path(__file__).resolve().parents[2] / ".env"   # backend/.env
    _load_dotenv(_env_file, override=False)
except ImportError:
    pass


class ModelTier(str, Enum):
    """Model capability tiers."""
    FAST     = "fast"      # Llama-3.1-8B  — simple/entity tasks
    STANDARD = "standard"  # gpt-oss-120b   — standard generation
    ADVANCED = "advanced"  # gpt-oss-120b   — complex reasoning


@dataclass
class ModelConfig:
    """Configuration for a specific model."""
    model_name: str
    temperature: float
    max_tokens: int
    timeout: int = 120
    max_retries: int = 3
    request_timeout: int = 60


@dataclass
class RAGConfig:
    """RAG pipeline configuration."""
    # BAAI/bge-large-en-v1.5 → 1024 dimensions
    embedding_model: str = field(
        default_factory=lambda: os.getenv("EMBED_MODEL", "BAAI/bge-large-en-v1.5")
    )
    embedding_dimensions: int = 1024
    chunk_size: int = 1000
    chunk_overlap: int = 200
    top_k: int = 5
    similarity_threshold: float = 0.75
    max_context_tokens: int = 8000
    batch_size: int = 100
    cache_ttl: int = 3600


@dataclass
class ChromaConfig:
    """ChromaDB vector store configuration."""
    persist_dir: str = field(default_factory=lambda: os.getenv("CHROMA_PERSIST_DIR", "./chroma_db"))
    collection_prefix: str = "sdd_org_"
    vector_size: int = 1024          # matches bge-large-en-v1.5
    distance: str = "cosine"


@dataclass
class RedisConfig:
    """Redis configuration for caching."""
    url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379"))
    embedding_cache_db: int = 1
    workflow_cache_db: int = 2
    ttl: int = 3600


@dataclass
class GuardrailsConfig:
    """Safety and guardrails configuration."""
    enable_pii_detection: bool = True
    enable_toxicity_filter: bool = True
    enable_injection_detection: bool = True
    max_input_tokens: int = 100_000
    max_output_tokens: int = 16_000
    rate_limit_per_org_per_minute: int = 60
    rate_limit_per_org_per_day: int = 5000


class AIConfig:
    """
    Central AI configuration — all models routed through DeepInfra's
    OpenAI-compatible endpoint.
    """

    # ── DeepInfra credentials ─────────────────────────────────────────────────
    DEEPINFRA_API_KEY: str  = os.getenv("DEEPINFRA_API_KEY", "")
    DEEPINFRA_BASE_URL: str = os.getenv(
        "DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai"
    )

    # ── Model names ───────────────────────────────────────────────────────────
    _LLM_MODEL:    str = os.getenv("LLM_MODEL",    "openai/gpt-oss-120b-Turbo")
    _EMBED_MODEL:  str = os.getenv("EMBED_MODEL",  "BAAI/bge-large-en-v1.5")
    _ENTITY_MODEL: str = os.getenv("ENTITY_MODEL", "meta-llama/Meta-Llama-3.1-8B-Instruct")

    # ── Model configurations per tier ─────────────────────────────────────────
    MODELS: Dict[str, ModelConfig] = {
        # Complex reasoning — main 120B model
        ModelTier.ADVANCED: ModelConfig(
            model_name=_LLM_MODEL,
            temperature=0.1,
            max_tokens=16_384,
            timeout=180,
            max_retries=3,
        ),
        # Standard generation — main 120B model
        ModelTier.STANDARD: ModelConfig(
            model_name=_LLM_MODEL,
            temperature=0.2,
            max_tokens=8_192,
            timeout=120,
            max_retries=3,
        ),
        # Fast / entity extraction — Llama 3.1 8B
        ModelTier.FAST: ModelConfig(
            model_name=_ENTITY_MODEL,
            temperature=0.1,
            max_tokens=4_096,
            timeout=60,
            max_retries=3,
        ),
    }

    # ── Task → tier mapping ───────────────────────────────────────────────────
    TASK_MODEL_MAP: Dict[str, ModelTier] = {
        "requirement_extraction":   ModelTier.ADVANCED,
        "requirement_structuring":  ModelTier.STANDARD,
        "epic_generation":          ModelTier.ADVANCED,
        "story_generation":         ModelTier.STANDARD,
        "sprint_planning":          ModelTier.ADVANCED,
        "task_breakdown":           ModelTier.STANDARD,
        "ui_spec_generation":       ModelTier.ADVANCED,
        "api_spec_generation":      ModelTier.ADVANCED,
        "qa_generation":            ModelTier.STANDARD,
        "documentation_generation": ModelTier.STANDARD,
        "release_notes_generation": ModelTier.FAST,
        "dependency_analysis":      ModelTier.STANDARD,
        "risk_detection":           ModelTier.ADVANCED,
        "estimation":               ModelTier.STANDARD,
        "traceability":             ModelTier.STANDARD,
        "confidence_scoring":       ModelTier.FAST,
        "validation":               ModelTier.FAST,
    }

    # ── Per-task temperature overrides ────────────────────────────────────────
    TEMPERATURE_OVERRIDES: Dict[str, float] = {
        "requirement_extraction": 0.0,   # deterministic extraction
        "api_spec_generation":    0.0,   # precise spec
        "risk_detection":         0.1,
        "story_generation":       0.3,   # allow creative variety
        "documentation_generation": 0.2,
    }

    # ── Sub-configs ───────────────────────────────────────────────────────────
    RAG:        RAGConfig        = RAGConfig()
    CHROMA:     ChromaConfig     = ChromaConfig()
    REDIS:      RedisConfig      = RedisConfig()
    GUARDRAILS: GuardrailsConfig = GuardrailsConfig()

    # ── LangSmith tracing (optional) ─────────────────────────────────────────
    LANGSMITH_API_KEY: Optional[str] = os.getenv("LANGSMITH_API_KEY")
    LANGSMITH_PROJECT: str           = os.getenv("LANGSMITH_PROJECT", "sdd-platform")
    LANGSMITH_TRACING: bool          = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"

    # ── Database (LangGraph checkpointing) ───────────────────────────────────
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/sdd_db",
    )

    # ── Workflow settings ─────────────────────────────────────────────────────
    MAX_CONCURRENT_AGENTS:      int   = int(os.getenv("MAX_CONCURRENT_AGENTS", "5"))
    WORKFLOW_TIMEOUT_SECONDS:   int   = int(os.getenv("WORKFLOW_TIMEOUT_SECONDS", "3600"))
    HUMAN_REVIEW_TIMEOUT_HOURS: int   = int(os.getenv("HUMAN_REVIEW_TIMEOUT_HOURS", "72"))

    # ── Confidence thresholds ─────────────────────────────────────────────────
    MIN_CONFIDENCE_THRESHOLD: float = float(os.getenv("MIN_CONFIDENCE_THRESHOLD", "0.6"))
    AUTO_APPROVE_THRESHOLD:   float = float(os.getenv("AUTO_APPROVE_THRESHOLD", "0.92"))

    # ── Helpers ───────────────────────────────────────────────────────────────

    @classmethod
    def get_model_config(cls, task: str) -> ModelConfig:
        """Return ModelConfig for a task, with temperature override applied."""
        tier = cls.TASK_MODEL_MAP.get(task, ModelTier.STANDARD)
        cfg  = cls.MODELS[tier]
        if task in cls.TEMPERATURE_OVERRIDES:
            cfg = copy(cfg)
            cfg.temperature = cls.TEMPERATURE_OVERRIDES[task]
        return cfg

    @classmethod
    def get_model_name(cls, task: str) -> str:
        return cls.get_model_config(task).model_name

    @classmethod
    def validate(cls) -> None:
        """Raise ValueError if required credentials are missing."""
        if not cls.DEEPINFRA_API_KEY:
            raise ValueError("DEEPINFRA_API_KEY environment variable is required")

    @classmethod
    def setup_langsmith(cls) -> None:
        """Configure LangSmith tracing if enabled."""
        if cls.LANGSMITH_TRACING and cls.LANGSMITH_API_KEY:
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ["LANGCHAIN_API_KEY"]     = cls.LANGSMITH_API_KEY
            os.environ["LANGCHAIN_PROJECT"]     = cls.LANGSMITH_PROJECT
