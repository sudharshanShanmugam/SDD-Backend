"""
Document Processing Sub-Workflow

Handles document ingestion, chunking, embedding, and indexing
before the main SDLC workflow begins.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)


class DocumentProcessingState(TypedDict):
    """State for the document processing workflow."""
    document_id: str
    document_content: str
    document_type: str  # pdf|docx|txt|markdown|confluence
    organization_id: str
    project_id: str

    # Processing results
    extracted_text: str
    cleaned_text: str
    chunks: List[Dict[str, Any]]
    embeddings_generated: bool
    indexed: bool

    # Metadata
    page_count: int
    word_count: int
    detected_language: str
    document_structure: Dict[str, Any]

    # Errors
    errors: List[str]
    current_stage: str


async def extract_text_node(state: DocumentProcessingState) -> Dict[str, Any]:
    """Extract plain text from various document formats."""
    logger.info("doc_workflow: extract_text | doc=%s", state["document_id"])

    content = state["document_content"]
    doc_type = state.get("document_type", "txt")

    try:
        # In production: use unstructured, pypdf2, python-docx etc.
        extracted = content.strip()

        word_count = len(extracted.split())
        page_count = max(1, word_count // 500)  # Rough estimate

        return {
            "extracted_text": extracted,
            "word_count": word_count,
            "page_count": page_count,
            "detected_language": "en",  # Would use langdetect in production
            "current_stage": "text_extracted",
        }
    except Exception as e:
        logger.exception("extract_text_node failed: %s", e)
        return {
            "errors": state.get("errors", []) + [str(e)],
            "current_stage": "error",
        }


async def clean_text_node(state: DocumentProcessingState) -> Dict[str, Any]:
    """Clean and normalize extracted text."""
    import re

    text = state.get("extracted_text", "")

    # Remove excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)

    # Remove page headers/footers (common patterns)
    text = re.sub(r"\bPage \d+ of \d+\b", "", text)
    text = re.sub(r"\bConfidential\b", "", text, flags=re.IGNORECASE)

    # Normalize unicode
    import unicodedata
    text = unicodedata.normalize("NFKD", text)

    return {
        "cleaned_text": text.strip(),
        "current_stage": "text_cleaned",
    }


async def chunk_and_embed_node(state: DocumentProcessingState) -> Dict[str, Any]:
    """Chunk the document and generate embeddings."""
    logger.info("doc_workflow: chunk_and_embed | doc=%s", state["document_id"])

    try:
        from app.ai.rag.chunker import DocumentChunker
        from app.ai.rag.embeddings import EmbeddingPipeline
        from app.ai.rag.vectorstore import VectorStoreManager

        chunker = DocumentChunker()
        pipeline = EmbeddingPipeline()
        vsm = VectorStoreManager()

        # Chunk
        chunks = await chunker.chunk_document(
            content=state["cleaned_text"],
            metadata={
                "document_id": state["document_id"],
                "project_id": state["project_id"],
                "organization_id": state["organization_id"],
                "document_type": state["document_type"],
            },
        )

        chunk_dicts = [
            {"content": c.page_content, "metadata": c.metadata}
            for c in chunks
        ]

        # Generate embeddings
        texts = [c.page_content for c in chunks]
        embeddings = await pipeline.embed_texts(texts)

        # Upsert to vector store
        collection = f"sdd_org_{state['organization_id']}"
        await vsm.upsert_documents(
            collection_name=collection,
            documents=chunks,
            embeddings=embeddings,
        )

        return {
            "chunks": chunk_dicts,
            "embeddings_generated": True,
            "indexed": True,
            "current_stage": "embedded_and_indexed",
        }
    except Exception as e:
        logger.exception("chunk_and_embed_node failed: %s", e)
        # Non-fatal: workflow can continue without RAG
        return {
            "chunks": [],
            "embeddings_generated": False,
            "indexed": False,
            "errors": state.get("errors", []) + [f"Embedding failed: {e}"],
            "current_stage": "embedding_skipped",
        }


async def analyze_structure_node(state: DocumentProcessingState) -> Dict[str, Any]:
    """Analyze document structure to improve extraction quality."""
    import re

    text = state.get("cleaned_text", "")

    # Detect sections
    section_patterns = [
        r"^#{1,3}\s+(.+)$",           # Markdown headers
        r"^(\d+\.)+\s+(.+)$",          # Numbered sections
        r"^[A-Z][A-Z\s]{5,}$",         # ALL CAPS headings
    ]

    sections = []
    for line in text.split("\n"):
        line = line.strip()
        for pattern in section_patterns:
            if re.match(pattern, line, re.MULTILINE):
                sections.append(line[:100])
                break

    structure = {
        "detected_sections": sections[:20],
        "has_tables": bool(re.search(r"\|.+\|", text)),
        "has_code_blocks": bool(re.search(r"```", text)),
        "has_numbered_lists": bool(re.search(r"^\d+\.", text, re.MULTILINE)),
        "estimated_reading_time_minutes": max(1, state.get("word_count", 0) // 200),
    }

    return {
        "document_structure": structure,
        "current_stage": "structure_analyzed",
    }


class DocumentProcessingWorkflow:
    """Document ingestion and preprocessing workflow."""

    def __init__(self):
        self._graph = None

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(DocumentProcessingState)

        graph.add_node("extract_text", extract_text_node)
        graph.add_node("clean_text", clean_text_node)
        graph.add_node("analyze_structure", analyze_structure_node)
        graph.add_node("chunk_and_embed", chunk_and_embed_node)

        graph.add_edge(START, "extract_text")
        graph.add_edge("extract_text", "clean_text")
        graph.add_edge("clean_text", "analyze_structure")
        graph.add_edge("analyze_structure", "chunk_and_embed")
        graph.add_edge("chunk_and_embed", END)

        return graph

    async def process(
        self,
        document_id: str,
        document_content: str,
        document_type: str,
        organization_id: str,
        project_id: str,
    ) -> DocumentProcessingState:
        """Process a document and return the final state."""
        if self._graph is None:
            self._graph = self._build_graph().compile()

        initial_state = DocumentProcessingState(
            document_id=document_id,
            document_content=document_content,
            document_type=document_type,
            organization_id=organization_id,
            project_id=project_id,
            extracted_text="",
            cleaned_text="",
            chunks=[],
            embeddings_generated=False,
            indexed=False,
            page_count=0,
            word_count=0,
            detected_language="en",
            document_structure={},
            errors=[],
            current_stage="initialized",
        )

        result = await self._graph.ainvoke(initial_state)
        return result
