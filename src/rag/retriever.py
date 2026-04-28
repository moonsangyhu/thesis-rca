"""
ChromaDB retriever for K8s RCA knowledge base.

Usage:
    from src.rag.retriever import KnowledgeRetriever
    retriever = KnowledgeRetriever()
    results = retriever.query("pod is OOMKilled and restarting", fault_type="F1")
"""
import logging
from dataclasses import dataclass
from typing import Optional

import chromadb
from chromadb.utils import embedding_functions

from .config import (
    CHROMA_DIR,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    FAULT_TYPES,
    SCORE_THRESHOLD,
    TOP_K,
)

logger = logging.getLogger(__name__)


@dataclass
class RetrievedDoc:
    """A single retrieved document chunk with metadata."""
    id: str
    content: str
    score: float          # cosine similarity (0~1, higher = more relevant)
    source: str           # file path
    filename: str
    category: str         # debugging / runbooks / known-issues
    title: str
    fault_types: str      # comma-separated F1,F2,...
    chunk_index: int
    chunk_total: int

    @property
    def short_source(self) -> str:
        """Return category/filename for display."""
        return f"{self.category}/{self.filename}"


class KnowledgeRetriever:
    """Query the ChromaDB knowledge base for relevant RCA documents."""

    def __init__(self):
        if not CHROMA_DIR.exists():
            raise RuntimeError(
                f"ChromaDB not found at {CHROMA_DIR}. "
                "Run: python -m src.rag.ingest"
            )

        self._client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self._embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
        self._collection = self._client.get_collection(
            name=COLLECTION_NAME,
            embedding_function=self._embed_fn,
        )
        logger.info(
            "KnowledgeRetriever loaded: %d chunks in collection",
            self._collection.count(),
        )

    def query(
        self,
        query_text: str,
        fault_type: Optional[str] = None,
        top_k: int = TOP_K,
        categories: Optional[list[str]] = None,
    ) -> list[RetrievedDoc]:
        """
        Query the knowledge base.

        Args:
            query_text: Natural language query (symptoms, error messages, etc.)
            fault_type: Optional fault type filter (e.g., "F1"). Expands query
                        with fault-specific keywords for better recall.
            top_k: Number of results to return.
            categories: Filter by category ("debugging", "runbooks", "known-issues").

        Returns:
            List of RetrievedDoc sorted by relevance (highest score first).
        """
        # Augment query with fault type keywords
        augmented_query = query_text
        if fault_type and fault_type in FAULT_TYPES:
            ft = FAULT_TYPES[fault_type]
            keywords = " ".join(ft["keywords"][:3])
            augmented_query = f"{query_text} {ft['description']} {keywords}"
            logger.debug("Augmented query for %s: %s", fault_type, augmented_query)

        # Build where filter
        where = None
        if categories:
            if len(categories) == 1:
                where = {"category": {"$eq": categories[0]}}
            else:
                where = {"category": {"$in": categories}}

        # Query ChromaDB
        results = self._collection.query(
            query_texts=[augmented_query],
            n_results=min(top_k * 2, self._collection.count()),  # over-fetch for filtering
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        docs = []
        for i, (doc_id, document, metadata, distance) in enumerate(
            zip(
                results["ids"][0],
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )
        ):
            # ChromaDB cosine distance: 0=identical, 2=opposite
            # Convert to similarity: 1 - (distance / 2) for cosine
            score = 1.0 - (distance / 2.0)

            if score < SCORE_THRESHOLD:
                logger.debug("Skipping low-score chunk %s (score=%.3f)", doc_id, score)
                continue

            docs.append(
                RetrievedDoc(
                    id=doc_id,
                    content=document,
                    score=score,
                    source=metadata.get("source", ""),
                    filename=metadata.get("filename", ""),
                    category=metadata.get("category", ""),
                    title=metadata.get("title", ""),
                    fault_types=metadata.get("fault_types", ""),
                    chunk_index=metadata.get("chunk_index", 0),
                    chunk_total=metadata.get("chunk_total", 1),
                )
            )

        # Sort by score descending and cap at top_k
        docs.sort(key=lambda d: d.score, reverse=True)
        return docs[:top_k]

    def query_by_fault(self, fault_type: str, top_k: int = TOP_K) -> list[RetrievedDoc]:
        """Retrieve all relevant docs for a given fault type."""
        if fault_type not in FAULT_TYPES:
            raise ValueError(f"Unknown fault type: {fault_type}. Valid: {list(FAULT_TYPES)}")

        ft = FAULT_TYPES[fault_type]
        query = f"{ft['name']} {ft['description']} {' '.join(ft['keywords'])}"
        return self.query(query, fault_type=fault_type, top_k=top_k)

    def get_runbook(self, fault_type: str) -> Optional[RetrievedDoc]:
        """Get the primary runbook for a fault type."""
        results = self.query(
            query_text=FAULT_TYPES.get(fault_type, {}).get("name", fault_type),
            fault_type=fault_type,
            top_k=1,
            categories=["runbooks"],
        )
        return results[0] if results else None

    def format_context(self, docs: list[RetrievedDoc], max_tokens: int = 3000) -> str:
        """Format retrieved docs as context string for LLM prompt.

        V9 환경 전제조건 (plan §3-5): chunk content가 이미 markdown H1(`# Title`)으로
        시작하면 prepended `# {doc.title}`를 생략하여 중복 출력을 방지한다.
        raw_v8 샘플(F11_t1_B 등)에서 `# Runbook: F11 - NetworkDelay Root Cause Analysis`가
        두 번 출력되는 패턴이 발견되어 본 단계에서 제거.
        """
        context_parts = []
        total_chars = 0
        char_limit = max_tokens * 4  # rough chars-per-token estimate

        for doc in docs:
            content = doc.content or ""
            content_starts_with_h1 = content.lstrip().startswith("# ")
            header = f"[Source: {doc.short_source} | Score: {doc.score:.2f}]\n"
            if not content_starts_with_h1:
                header += f"# {doc.title}\n"
            section = header + content + "\n"

            if total_chars + len(section) > char_limit:
                # Truncate last doc to fit
                remaining = char_limit - total_chars
                if remaining > 200:
                    context_parts.append(section[:remaining] + "\n... (truncated)")
                break

            context_parts.append(section)
            total_chars += len(section)

        return "\n---\n".join(context_parts)

    @property
    def count(self) -> int:
        return self._collection.count()
