"""
RAG (Retrieval-Augmented Generation) Package

Provides embedding, vector storage, chunking, retrieval, and indexing
for the SDD platform's contextual AI capabilities.
"""

from app.ai.rag.chunker import DocumentChunker, SmartDocumentChunker, document_chunker
from app.ai.rag.embeddings import EmbeddingPipeline, embedding_pipeline
from app.ai.rag.indexer import DocumentIndexer, document_indexer
from app.ai.rag.retriever import ContextualRetriever, contextual_retriever
from app.ai.rag.vectorstore import SimilarChunk, VectorStoreManager, vector_store_manager

__all__ = [
    # Classes
    "DocumentChunker",
    "SmartDocumentChunker",
    "EmbeddingPipeline",
    "VectorStoreManager",
    "SimilarChunk",
    "ContextualRetriever",
    "DocumentIndexer",
    # Singletons
    "document_chunker",
    "embedding_pipeline",
    "vector_store_manager",
    "contextual_retriever",
    "document_indexer",
]
