"""
Document ingestion pipeline: load markdown files → chunk → embed → store in ChromaDB.

Usage:
    python -m src.rag.ingest              # ingest all docs
    python -m src.rag.ingest --reset      # drop collection and re-ingest
    python -m src.rag.ingest --dry-run    # show what would be ingested
"""
import argparse
import hashlib
import logging
import re
import sys
from pathlib import Path
from typing import Iterator

import chromadb
from chromadb.utils import embedding_functions
from tqdm import tqdm

from .config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    CHROMA_DIR,
    COLLECTION_NAME,
    DEBUGGING_DIR,
    EMBEDDING_MODEL,
    KNOWN_ISSUES_DIR,
    MIN_CHUNK_SIZE,
    RUNBOOKS_DIR,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def iter_doc_files() -> Iterator[tuple[str, Path]]:
    """Yield (category, path) for all markdown files in docs/."""
    dirs = {
        "debugging": DEBUGGING_DIR,
        "runbooks": RUNBOOKS_DIR,
        "known-issues": KNOWN_ISSUES_DIR,
    }
    for category, doc_dir in dirs.items():
        if not doc_dir.exists():
            logger.warning("Directory not found: %s", doc_dir)
            continue
        for path in sorted(doc_dir.glob("*.md")):
            yield category, path


def extract_metadata(content: str, path: Path, category: str) -> dict:
    """Extract title and fault type tags from markdown content."""
    metadata = {
        "source": str(path),
        "filename": path.name,
        "category": category,
        "fault_types": "",
    }

    # Extract title from first H1
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    metadata["title"] = title_match.group(1).strip() if title_match else path.stem

    # Detect referenced fault types (F1~F10)
    fault_refs = re.findall(r"\bF([1-9]|10)\b", content)
    if fault_refs:
        metadata["fault_types"] = ",".join(sorted(set(f"F{f}" for f in fault_refs)))

    # Extract Issue ID for known-issues (KI-XXX)
    ki_match = re.search(r"KI-\d+", content)
    if ki_match:
        metadata["issue_id"] = ki_match.group(0)

    return metadata


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Split text into overlapping chunks, respecting markdown section boundaries.
    Prefer splitting at heading boundaries (##, ###) before character limits.
    """
    # Split at section headings first
    sections = re.split(r"\n(?=#{1,3}\s)", text)

    chunks = []
    current_chunk = ""

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # If section fits in remaining space, append
        if len(current_chunk) + len(section) <= chunk_size:
            current_chunk = (current_chunk + "\n\n" + section).strip()
        else:
            # Save current chunk if non-empty
            if len(current_chunk) >= MIN_CHUNK_SIZE:
                chunks.append(current_chunk)

            # If section itself is larger than chunk_size, split by paragraphs
            if len(section) > chunk_size:
                paragraphs = re.split(r"\n\n+", section)
                current_chunk = ""
                for para in paragraphs:
                    para = para.strip()
                    if not para:
                        continue
                    if len(current_chunk) + len(para) <= chunk_size:
                        current_chunk = (current_chunk + "\n\n" + para).strip()
                    else:
                        if len(current_chunk) >= MIN_CHUNK_SIZE:
                            chunks.append(current_chunk)
                        # Hard split with overlap if paragraph is still too large
                        if len(para) > chunk_size:
                            for i in range(0, len(para), chunk_size - overlap):
                                sub = para[i : i + chunk_size]
                                if len(sub) >= MIN_CHUNK_SIZE:
                                    chunks.append(sub)
                            current_chunk = para[-(overlap):]
                        else:
                            current_chunk = para
            else:
                # Start new chunk with overlap from end of previous
                overlap_text = current_chunk[-overlap:] if overlap else ""
                current_chunk = (overlap_text + "\n\n" + section).strip() if overlap_text else section

    # Flush last chunk
    if len(current_chunk) >= MIN_CHUNK_SIZE:
        chunks.append(current_chunk)

    return chunks


def doc_id(path: Path, chunk_index: int) -> str:
    """Generate a stable unique ID for a chunk."""
    h = hashlib.md5(str(path).encode()).hexdigest()[:8]
    return f"{path.stem}_{h}_{chunk_index:04d}"


def ingest(reset: bool = False, dry_run: bool = False) -> int:
    """
    Main ingestion function.
    Returns total number of chunks ingested.
    """
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    if reset:
        try:
            client.delete_collection(COLLECTION_NAME)
            logger.info("Dropped existing collection: %s", COLLECTION_NAME)
        except Exception:
            pass

    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )

    doc_files = list(iter_doc_files())
    logger.info("Found %d document files", len(doc_files))

    total_chunks = 0
    batch_ids = []
    batch_docs = []
    batch_metas = []
    BATCH_SIZE = 50

    for category, path in tqdm(doc_files, desc="Ingesting documents"):
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to read %s: %s", path, e)
            continue

        metadata = extract_metadata(content, path, category)
        chunks = chunk_text(content)

        if dry_run:
            logger.info("[DRY-RUN] %s → %d chunks", path.name, len(chunks))
            total_chunks += len(chunks)
            continue

        for i, chunk in enumerate(chunks):
            cid = doc_id(path, i)
            chunk_meta = {**metadata, "chunk_index": i, "chunk_total": len(chunks)}
            batch_ids.append(cid)
            batch_docs.append(chunk)
            batch_metas.append(chunk_meta)

            if len(batch_ids) >= BATCH_SIZE:
                collection.upsert(ids=batch_ids, documents=batch_docs, metadatas=batch_metas)
                total_chunks += len(batch_ids)
                batch_ids, batch_docs, batch_metas = [], [], []

    # Flush remaining batch
    if batch_ids and not dry_run:
        collection.upsert(ids=batch_ids, documents=batch_docs, metadatas=batch_metas)
        total_chunks += len(batch_ids)

    if not dry_run:
        logger.info(
            "Ingestion complete: %d chunks in collection '%s' (total: %d)",
            total_chunks,
            COLLECTION_NAME,
            collection.count(),
        )

    return total_chunks


def main():
    parser = argparse.ArgumentParser(description="Ingest K8s RCA documents into ChromaDB")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate collection")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be ingested")
    args = parser.parse_args()

    count = ingest(reset=args.reset, dry_run=args.dry_run)
    print(f"\nTotal chunks: {count}")
    sys.exit(0)


if __name__ == "__main__":
    main()
