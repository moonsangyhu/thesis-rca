# docs/ — RAG Knowledge Base

## Purpose

This directory contains **65 curated Kubernetes troubleshooting documents** that serve as the retrieval-augmented generation (RAG) knowledge base for the RCA pipeline. These documents are ingested into ChromaDB as vector embeddings and retrieved at inference time to provide domain-specific context to the LLM.

The RAG knowledge base is a core component of **System B (Proposed)** — it enables the LLM to ground its root cause analysis in documented failure patterns, operational runbooks, and known cluster-specific issues rather than relying solely on parametric knowledge.

## Structure

| Directory | Count | Description |
|-----------|-------|-------------|
| `debugging/` | 20 | General Kubernetes failure pattern guides — symptoms, investigation steps, and resolution for common pod/node/network/storage issues |
| `runbooks/` | 20 | Fault-specific RCA procedures (F1–F10) and operational restore playbooks with step-by-step commands |
| `known-issues/` | 25 | Documented cluster-specific issues encountered during setup, plus common Kubernetes operational pitfalls |

## Ingestion

Documents are chunked by markdown section boundaries (512 chars, 64 overlap) and embedded using `all-MiniLM-L6-v2` into ChromaDB.

```bash
source .venv/bin/activate
python -m src.rag.ingest --reset    # Full re-ingestion (1,243 chunks)
python -m src.rag.ingest            # Incremental (skip existing)
```

## Document Design Principles

1. **Actionable over theoretical** — Each document includes concrete `kubectl` commands, not just conceptual explanations
2. **Cluster-specific context** — Known issues reference our actual Cilium/FluxCD/local-path-provisioner environment
3. **Structured for retrieval** — Consistent markdown headings enable section-aware chunking with meaningful boundaries
4. **Cross-referenced** — Runbooks reference debugging guides; known issues link to relevant runbooks
