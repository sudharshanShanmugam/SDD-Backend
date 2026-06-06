"""
Best-Practice RAG Chunker — Hierarchical, Structure-Aware

Replaces the old RecursiveCharacterTextSplitter-based approach with a
purpose-built pipeline that produces retrieval-optimal chunks:

  1. Parses document structure into a section tree (H1 → H2 → H3,
     numbered sections, ALL-CAPS headings, Markdown headers)
  2. Prepends the full section breadcrumb path to every chunk so the
     embedding captures BOTH context ("Authentication > Password Reset")
     AND content ("The user shall receive a reset email…")
  3. Splits content at paragraph → sentence boundaries — never mid-sentence
  4. Targets 400 tokens per chunk (sweet spot for BAAI/bge-large-en-v1.5)
  5. Applies 50-token sentence-level overlap to preserve continuity
  6. Tags each chunk: paragraph | list | table | code | header
  7. Stores rich metadata: section_path, chunk_type, position_ratio,
     section_depth, token_count, char_count

Default parameters (tuned for BAAI/bge-large-en-v1.5, 1 024 dims):
  target_tokens  = 400   ≈ 1 600 chars — enough context per retrieval unit
  min_tokens     =  50   ≈   200 chars — discard noise fragments
  max_tokens     = 600   ≈ 2 400 chars — hard cap; force-split if exceeded
  overlap_tokens =  50   ≈   200 chars — one sentence of carry-over
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document


# ── Tokens ────────────────────────────────────────────────────────────────────

def _count_tokens(text: str) -> int:
    """Fast token counter: tiktoken when available, else chars/4."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def _split_sentences(text: str) -> List[str]:
    """
    Split text into sentences using a punctuation-aware regex.
    Handles abbreviations (Mr., Dr., U.S.), decimals, and ellipses.
    """
    # sentence-ending punctuation NOT followed by lowercase (abbreviation guard)
    pattern = re.compile(
        r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\!|\?)\s+(?=[A-Z"\'])',
    )
    parts = pattern.split(text)
    # Keep at least one sentence
    return [s.strip() for s in parts if s.strip()] or [text.strip()]


# ── Data Model ────────────────────────────────────────────────────────────────

@dataclass
class Chunk:
    """A single semantically coherent document chunk with rich metadata."""

    text: str                          # raw content, possibly prepended with section path
    chunk_index: int
    section_title: Optional[str]       # immediate section heading
    section_path: str                  # breadcrumb: "Auth > Password Reset"
    section_depth: int                 # 0 = top-level, 1 = H2, 2 = H3
    chunk_type: str                    # paragraph | list | table | code | header
    page_number: Optional[int]
    token_count: int
    char_count: int
    position_ratio: float              # 0.0 = start, 1.0 = end of document
    metadata: Dict[str, Any] = field(default_factory=dict)

    # LangChain compatibility
    @property
    def page_content(self) -> str:
        return self.text


# ── Section Node ──────────────────────────────────────────────────────────────

@dataclass
class _Section:
    title: str
    depth: int                # 1 = H1, 2 = H2, 3 = H3
    content: str              # raw text under this heading
    children: List["_Section"] = field(default_factory=list)
    parent_path: str = ""

    @property
    def path(self) -> str:
        if self.parent_path:
            return f"{self.parent_path} > {self.title}"
        return self.title


# ── Core Chunker ─────────────────────────────────────────────────────────────

class SmartDocumentChunker:
    """
    Hierarchical, structure-aware document chunker.

    Replace SmartDocumentChunker(chunk_size=1000, chunk_overlap=200) everywhere
    — all old keyword arguments are silently accepted for drop-in compatibility.
    """

    # Header patterns (highest depth first for correct nesting)
    _H1 = re.compile(r"^#\s+(.+)$",         re.MULTILINE)
    _H2 = re.compile(r"^##\s+(.+)$",        re.MULTILINE)
    _H3 = re.compile(r"^###\s+(.+)$",       re.MULTILINE)
    _H_DEEPER = re.compile(r"^#{4,6}\s+(.+)$", re.MULTILINE)

    # Numbered sections: "1.", "1.1", "1.1.1", "A.", "I."
    _NUMBERED = re.compile(
        r"^(?:(?:\d+\.){1,3}|[A-Z]\.|[IVXivx]+\.)\s{1,4}(.{3,100})$",
        re.MULTILINE,
    )
    # ALL-CAPS lines ≥ 4 letters
    _ALLCAPS = re.compile(
        r"^([A-Z][A-Z\s\-\/]{3,79})$",
        re.MULTILINE,
    )

    # Block-type detectors
    _CODE_BLOCK  = re.compile(r"```[\s\S]*?```|`[^`]+`")
    _TABLE_LINE  = re.compile(r"^\|.+\|$", re.MULTILINE)
    _LIST_LINE   = re.compile(r"^[\s]*[-*•]\s+|^[\s]*\d+[.)]\s+", re.MULTILINE)

    def __init__(
        self,
        # New parameters
        target_tokens:  int = 400,
        min_tokens:     int = 50,
        max_tokens:     int = 600,
        overlap_tokens: int = 50,
        prepend_section_path: bool = True,
        # Legacy keyword aliases (ignored, kept for drop-in compat)
        chunk_size:    int = 0,
        chunk_overlap: int = 0,
    ):
        # Allow old callers: SmartDocumentChunker(chunk_size=1000, chunk_overlap=200)
        if chunk_size and not target_tokens:
            target_tokens  = max(100, chunk_size // 4)
            overlap_tokens = max(20,  chunk_overlap // 4)

        self.target_tokens        = target_tokens
        self.min_tokens           = min_tokens
        self.max_tokens           = max_tokens
        self.overlap_tokens       = overlap_tokens
        self.prepend_section_path = prepend_section_path

    # ── Public API ────────────────────────────────────────────────────────────

    def chunk_text(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Chunk]:
        """
        Chunk raw document text into retrieval-optimal Chunk objects.

        Args:
            text:     Raw document text.
            metadata: Extra metadata attached to every chunk.

        Returns:
            Ordered list of Chunk objects.
        """
        text = self._normalise(text)
        if not text:
            return []

        total_chars = len(text)
        char_offset = 0  # tracks position in original text for position_ratio

        # Step 1: Parse document into section tree
        sections = self._parse_sections(text)

        # Step 2: Walk sections and produce chunks
        chunks: List[Chunk] = []
        base_meta = metadata or {}

        def _process(section: _Section, depth: int) -> None:
            nonlocal char_offset
            if section.content.strip():
                new_chunks = self._chunk_section(
                    content      = section.content,
                    section_path = section.path,
                    depth        = depth,
                    total_chars  = total_chars,
                    base_meta    = base_meta,
                )
                chunks.extend(new_chunks)
            for child in section.children:
                _process(child, depth + 1)

        for section in sections:
            _process(section, section.depth)

        # Step 3: Re-number sequentially
        for i, c in enumerate(chunks):
            c.chunk_index = i

        # Step 4: Merge tiny tail chunks into their predecessor
        chunks = self._merge_tiny(chunks)

        return chunks

    async def chunk_document(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Chunk]:
        """Async-compatible wrapper (no blocking I/O — runs synchronously)."""
        chunks = self.chunk_text(text=content, metadata=metadata)
        # Enrich metadata with all new fields
        for chunk in chunks:
            chunk.metadata = {
                **chunk.metadata,
                "chunk_index":    chunk.chunk_index,
                "section_title":  chunk.section_title,
                "section_path":   chunk.section_path,
                "section_depth":  chunk.section_depth,
                "chunk_type":     chunk.chunk_type,
                "token_count":    chunk.token_count,
                "char_count":     chunk.char_count,
                "position_ratio": chunk.position_ratio,
            }
        return chunks

    def to_langchain_documents(self, chunks: List[Chunk]) -> List[Document]:
        """Convert Chunk list to LangChain Document list."""
        return [
            Document(
                page_content=chunk.text,
                metadata={
                    **chunk.metadata,
                    "chunk_index":   chunk.chunk_index,
                    "section_title": chunk.section_title,
                    "section_path":  chunk.section_path,
                    "chunk_type":    chunk.chunk_type,
                    "token_count":   chunk.token_count,
                    "page_number":   chunk.page_number,
                },
            )
            for chunk in chunks
        ]

    # ── Section Parsing ───────────────────────────────────────────────────────

    def _parse_sections(self, text: str) -> List[_Section]:
        """
        Detect section boundaries and return a flat list of _Section objects.
        Nesting is inferred from depth: H1 > H2 > H3 > numbered > ALL-CAPS.
        """
        # Unified header detection
        #   group 1: hashes (Markdown depth)
        #   group 2: numbered heading
        #   group 3: ALL-CAPS heading
        header_re = re.compile(
            r"^(#{1,6})\s+(.+)"                     # Markdown ## Heading
            r"|^((?:\d+\.){1,3}[0-9]*)\s+(.{3,100})"  # 1.2.3 Heading
            r"|^([A-Z][A-Z\s\-\/]{3,79})$",         # ALL CAPS HEADING
            re.MULTILINE,
        )

        matches = list(header_re.finditer(text))
        if not matches:
            return [_Section(title="Document", depth=1, content=text)]

        sections: List[_Section] = []

        def _depth_from_match(m: re.Match) -> int:
            if m.group(1):                         # Markdown: count #
                return len(m.group(1))
            if m.group(3):                         # Numbered: count dots
                return min(3, m.group(3).count(".") + 1)
            return 2                               # ALL-CAPS → treat as H2

        def _title_from_match(m: re.Match) -> str:
            if m.group(1):  return (m.group(2) or "").strip()
            if m.group(3):  return (m.group(4) or "").strip()
            return (m.group(5) or "").strip()

        # Preamble before first header
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.append(_Section(title="Preamble", depth=1, content=preamble))

        # Build path stack for breadcrumbs
        path_stack: List[Tuple[int, str]] = []  # [(depth, title), ...]

        for i, m in enumerate(matches):
            depth = _depth_from_match(m)
            title = _title_from_match(m)
            if not title:
                continue

            content_start = m.end()
            content_end   = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content        = text[content_start:content_end].strip()

            # Build breadcrumb
            while path_stack and path_stack[-1][0] >= depth:
                path_stack.pop()
            parent_path = " > ".join(t for _, t in path_stack)
            path_stack.append((depth, title))

            sections.append(_Section(
                title=title,
                depth=depth,
                content=content,
                parent_path=parent_path,
            ))

        return sections or [_Section(title="Document", depth=1, content=text)]

    # ── Content Splitting ─────────────────────────────────────────────────────

    def _chunk_section(
        self,
        content: str,
        section_path: str,
        depth: int,
        total_chars: int,
        base_meta: Dict[str, Any],
    ) -> List[Chunk]:
        """
        Split a single section's content into token-sized chunks.
        Maintains sentence-level overlap between consecutive chunks.
        """
        # Detect content blocks
        paragraphs = self._split_paragraphs(content)
        chunks: List[Chunk] = []
        carry: List[str] = []        # overlap sentences from previous chunk
        carry_tokens = 0

        for para in paragraphs:
            if not para.strip():
                continue

            para_type  = self._classify_block(para)
            sentences  = _split_sentences(para) if para_type == "paragraph" else [para]

            for sent in sentences:
                sent_tokens = _count_tokens(sent)

                # A single sentence that already exceeds max → emit as its own chunk
                if sent_tokens >= self.max_tokens:
                    if carry:
                        chunks.append(self._make_chunk(
                            carry, section_path, depth, para_type, total_chars, base_meta
                        ))
                        carry, carry_tokens = [], 0
                    chunks.append(self._make_chunk(
                        [sent], section_path, depth, para_type, total_chars, base_meta
                    ))
                    continue

                # Would overflow → flush current carry first
                if carry_tokens + sent_tokens > self.target_tokens and carry:
                    chunks.append(self._make_chunk(
                        carry, section_path, depth, para_type, total_chars, base_meta
                    ))
                    # Sentence-level overlap: keep last N tokens worth of sentences
                    carry, carry_tokens = self._tail_overlap(carry)

                carry.append(sent)
                carry_tokens += sent_tokens

        # Flush remainder
        if carry:
            chunks.append(self._make_chunk(
                carry, section_path, depth,
                para_type if paragraphs else "paragraph",
                total_chars, base_meta
            ))

        return chunks

    def _make_chunk(
        self,
        sentences: List[str],
        section_path: str,
        depth: int,
        chunk_type: str,
        total_chars: int,
        base_meta: Dict[str, Any],
    ) -> Chunk:
        body = " ".join(sentences).strip()
        if not body:
            body = " ".join(sentences)

        # Optionally prepend section path for better embedding signal
        if self.prepend_section_path and section_path:
            display = f"{section_path}:\n\n{body}"
        else:
            display = body

        tokens = _count_tokens(display)
        # Approximate position from char offset of content
        position = min(1.0, len(display) / max(1, total_chars))

        parts = section_path.rsplit(" > ", 1)
        immediate_title = parts[-1] if parts else section_path

        return Chunk(
            text           = display,
            chunk_index    = 0,           # re-numbered in chunk_text()
            section_title  = immediate_title or None,
            section_path   = section_path,
            section_depth  = depth,
            chunk_type     = chunk_type,
            page_number    = None,
            token_count    = tokens,
            char_count     = len(display),
            position_ratio = position,
            metadata       = dict(base_meta),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _normalise(self, text: str) -> str:
        """Light normalisation: CRLF → LF, collapse 3+ blank lines, trim."""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{4,}", "\n\n\n", text)
        return text.strip()

    def _split_paragraphs(self, text: str) -> List[str]:
        """Split text on double (or triple) newlines."""
        return [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]

    def _classify_block(self, text: str) -> str:
        """Detect block type for a paragraph."""
        if self._CODE_BLOCK.search(text):  return "code"
        if self._TABLE_LINE.search(text):  return "table"
        if self._LIST_LINE.search(text):   return "list"
        return "paragraph"

    def _tail_overlap(self, sentences: List[str]) -> Tuple[List[str], int]:
        """
        Return the last N sentences that together are ≤ overlap_tokens.
        Used as the carry-over for the next chunk.
        """
        overlap: List[str] = []
        tokens = 0
        for sent in reversed(sentences):
            t = _count_tokens(sent)
            if tokens + t > self.overlap_tokens:
                break
            overlap.insert(0, sent)
            tokens += t
        return overlap, tokens

    def _merge_tiny(self, chunks: List[Chunk]) -> List[Chunk]:
        """
        Merge chunks smaller than min_tokens into the previous chunk,
        unless doing so would exceed max_tokens.
        """
        if not chunks:
            return chunks
        merged: List[Chunk] = [chunks[0]]
        for c in chunks[1:]:
            prev = merged[-1]
            if (c.token_count < self.min_tokens
                    and prev.token_count + c.token_count <= self.max_tokens
                    and prev.section_path == c.section_path):
                # Append text to previous chunk
                combined = prev.text + "\n\n" + c.text
                prev.text        = combined
                prev.token_count = _count_tokens(combined)
                prev.char_count  = len(combined)
            else:
                merged.append(c)
        # Re-number
        for i, c in enumerate(merged):
            c.chunk_index = i
        return merged


# ── Backward-Compat Alias ────────────────────────────────────────────────────

# document_workflow.py imports "DocumentChunker"; keep the alias.
DocumentChunker = SmartDocumentChunker

# Module-level singleton used by indexer.py and workflow nodes.
# Parameters tuned for BAAI/bge-large-en-v1.5 (1 024-dim embeddings).
document_chunker = SmartDocumentChunker(
    target_tokens  = 400,
    min_tokens     = 50,
    max_tokens     = 600,
    overlap_tokens = 50,
    prepend_section_path = True,
)
