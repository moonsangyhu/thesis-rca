"""
RAG pipeline: retrieve relevant docs + generate RCA with LLM.

Usage:
    from src.rag.pipeline import RCAPipeline

    pipeline = RCAPipeline()
    result = pipeline.analyze(
        symptoms="frontend pod OOMKilled, 3 restarts in last hour",
        fault_type="F1",
        k8s_context={...},  # optional: events, logs, metrics
    )
    print(result.root_cause)
    print(result.remediation)
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from .config import FAULT_TYPES, TOP_K
from .retriever import KnowledgeRetriever, RetrievedDoc

logger = logging.getLogger(__name__)


@dataclass
class RCAResult:
    """Result of a root cause analysis."""
    fault_type: str
    fault_name: str
    root_cause: str
    confidence: float          # 0.0 ~ 1.0
    remediation: list[str]     # ordered steps
    relevant_docs: list[RetrievedDoc] = field(default_factory=list)
    raw_response: str = ""

    def to_dict(self) -> dict:
        return {
            "fault_type": self.fault_type,
            "fault_name": self.fault_name,
            "root_cause": self.root_cause,
            "confidence": self.confidence,
            "remediation": self.remediation,
            "relevant_docs": [
                {
                    "source": d.short_source,
                    "title": d.title,
                    "score": round(d.score, 3),
                }
                for d in self.relevant_docs
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


SYSTEM_PROMPT = """\
You are a Kubernetes Site Reliability Engineer specializing in root cause analysis.
Given symptoms, K8s diagnostic context, and relevant knowledge base articles,
identify the root cause and provide a concrete remediation plan.

Output format (JSON):
{
  "root_cause": "one-sentence root cause statement",
  "confidence": 0.0-1.0,
  "detail": "2-3 sentences with technical explanation",
  "remediation": ["step 1", "step 2", ...]
}

Be concise and actionable. Focus on the most likely root cause based on evidence.
"""

RCA_PROMPT_TEMPLATE = """\
## Fault Type
{fault_type}: {fault_name}
{fault_description}

## Observed Symptoms
{symptoms}

## K8s Diagnostic Context
{k8s_context}

## Relevant Knowledge Base Articles
{knowledge_context}

## Task
Analyze the symptoms and context above. Identify the root cause and provide
a step-by-step remediation plan. Output valid JSON only.
"""


class RCAPipeline:
    """
    Full RAG-based RCA pipeline.

    Requires an LLM client. Supports OpenAI-compatible APIs and Anthropic Claude.
    """

    def __init__(
        self,
        llm_client=None,
        model: str = "claude-sonnet-4-6",
        top_k: int = TOP_K,
    ):
        """
        Args:
            llm_client: Optional pre-configured LLM client.
                        If None, auto-detects from environment (ANTHROPIC_API_KEY or OPENAI_API_KEY).
            model: LLM model name.
            top_k: Number of knowledge base docs to retrieve.
        """
        self.retriever = KnowledgeRetriever()
        self.model = model
        self.top_k = top_k
        self._llm = llm_client or self._init_llm()

    def _init_llm(self):
        """Auto-initialize LLM client from environment."""
        import os

        if os.environ.get("ANTHROPIC_API_KEY"):
            try:
                import anthropic
                logger.info("Using Anthropic Claude: %s", self.model)
                return anthropic.Anthropic()
            except ImportError:
                logger.warning("anthropic package not installed")

        if os.environ.get("OPENAI_API_KEY"):
            try:
                from openai import OpenAI
                logger.info("Using OpenAI: %s", self.model)
                return OpenAI()
            except ImportError:
                logger.warning("openai package not installed")

        logger.warning("No LLM client configured. RAG retrieval only mode.")
        return None

    def _call_llm(self, prompt: str) -> str:
        """Call LLM and return response text."""
        if self._llm is None:
            raise RuntimeError("No LLM client configured")

        import anthropic
        from openai import OpenAI

        if isinstance(self._llm, anthropic.Anthropic):
            response = self._llm.messages.create(
                model=self.model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text

        if isinstance(self._llm, OpenAI):
            response = self._llm.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1024,
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content

        raise TypeError(f"Unsupported LLM client type: {type(self._llm)}")

    def retrieve(
        self,
        symptoms: str,
        fault_type: Optional[str] = None,
    ) -> list[RetrievedDoc]:
        """Retrieve relevant knowledge base documents."""
        return self.retriever.query(symptoms, fault_type=fault_type, top_k=self.top_k)

    def analyze(
        self,
        symptoms: str,
        fault_type: Optional[str] = None,
        k8s_context: Optional[dict] = None,
    ) -> RCAResult:
        """
        Run full RCA pipeline.

        Args:
            symptoms: Human-readable description of observed symptoms.
            fault_type: Known fault type (F1~F10) if pre-classified, else None.
            k8s_context: Optional dict with keys like 'events', 'logs', 'metrics',
                         'pod_status', 'node_status'.

        Returns:
            RCAResult with root cause, confidence, and remediation steps.
        """
        # Step 1: Retrieve relevant knowledge
        docs = self.retrieve(symptoms, fault_type=fault_type)
        logger.info("Retrieved %d docs for RCA", len(docs))

        # Step 2: Format context
        knowledge_context = self.retriever.format_context(docs)
        context_str = self._format_k8s_context(k8s_context or {})

        # Step 3: Build prompt
        ft_info = FAULT_TYPES.get(fault_type, {}) if fault_type else {}
        prompt = RCA_PROMPT_TEMPLATE.format(
            fault_type=fault_type or "UNKNOWN",
            fault_name=ft_info.get("name", "Unknown fault"),
            fault_description=ft_info.get("description", ""),
            symptoms=symptoms,
            k8s_context=context_str or "No additional context provided.",
            knowledge_context=knowledge_context or "No relevant docs found.",
        )

        # Step 4: Call LLM (if available)
        raw_response = ""
        root_cause = "See retrieved knowledge base articles."
        confidence = 0.0
        remediation = []

        if self._llm:
            try:
                raw_response = self._call_llm(prompt)
                parsed = json.loads(raw_response)
                root_cause = parsed.get("root_cause", "")
                confidence = float(parsed.get("confidence", 0.0))
                remediation = parsed.get("remediation", [])
            except Exception as e:
                logger.error("LLM call failed: %s", e)
                root_cause = f"LLM error: {e}"
        else:
            # Retrieval-only mode: summarize top doc
            if docs:
                root_cause = f"Based on knowledge base: {docs[0].title}"
                confidence = docs[0].score
                remediation = [f"Refer to: {docs[0].short_source}"]

        return RCAResult(
            fault_type=fault_type or "UNKNOWN",
            fault_name=ft_info.get("name", "Unknown"),
            root_cause=root_cause,
            confidence=confidence,
            remediation=remediation,
            relevant_docs=docs,
            raw_response=raw_response,
        )

    @staticmethod
    def _format_k8s_context(ctx: dict) -> str:
        """Format K8s diagnostic context dict as readable string."""
        if not ctx:
            return ""
        parts = []
        for key, value in ctx.items():
            if isinstance(value, (dict, list)):
                parts.append(f"### {key}\n```\n{json.dumps(value, indent=2)}\n```")
            else:
                parts.append(f"### {key}\n{value}")
        return "\n\n".join(parts)
