# src/ — RCA Pipeline Source Code

## Purpose

This directory contains the Python pipeline that performs automated root cause analysis on Kubernetes cluster failures. The pipeline collects observability data (metrics, logs, events), optionally augments it with GitOps context, retrieves relevant knowledge via RAG, and invokes an LLM to produce structured RCA output.

The pipeline implements both experimental conditions:

- **System A (Baseline)**: `collector` → `processor` → `llm` (observability-only)
- **System B (Proposed)**: `collector` → `processor` → `rag` → `llm` (observability + GitOps context + RAG)

## Modules

| Module | Status | Description |
|--------|--------|-------------|
| `collector/` | Planned | Collects Prometheus metrics, Loki logs, kubectl events, and GitOps state (FluxCD/ArgoCD) |
| `processor/` | Planned | Preprocesses and extracts features from collected signals; builds structured context for LLM |
| `llm/` | Planned | LLM inference wrapper — constructs prompts, calls Anthropic/OpenAI API, parses structured RCA output |
| `rag/` | **Complete** | ChromaDB-based RAG pipeline — document ingestion, embedding, retrieval, and context formatting |

## RAG Module (`src/rag/`)

The only fully implemented module. Provides retrieval-augmented generation for the RCA pipeline.

| File | Role |
|------|------|
| `config.py` | Fault type definitions (F1–F10), ChromaDB/embedding/chunking parameters |
| `ingest.py` | Markdown → section-aware chunks → ChromaDB with `all-MiniLM-L6-v2` embeddings |
| `retriever.py` | Cosine similarity search with fault-type keyword augmentation and category filtering |
| `pipeline.py` | End-to-end RAG + LLM RCA pipeline with structured JSON output |

```bash
# Usage
source .venv/bin/activate
python -m src.rag.ingest --reset          # Ingest docs into ChromaDB
python -c "from src.rag import KnowledgeRetriever; r = KnowledgeRetriever(); print(r.query('OOMKilled pod restart'))"
```
