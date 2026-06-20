"""5-arm context assembler with length orthogonalization (V2.2).

Each (fault, trial) injects/collects once; all 5 arms share the same signals.
A single RCAContext is built with system="B" so obs + gitops + rag fields are
populated; the assembler then carves out per-arm context strings.

Length orthogonalization (plan §2-1): the GitOps block and the RAG block are
each fit to the same T_block token budget (pad/truncate). C5_placebo fills
2*T_block tokens with neutral boilerplate so total added length matches C4 but
carries zero semantic signal.

Token approximation: tokens ~= len(chars) // 4 (plan §5 sanction).
"""
import re

# Neutral boilerplate sentences used to pad blocks / build the placebo.
# Intentionally generic SRE-flavored filler with NO fault-specific signal and
# NO real diff from any other fault (avoids label-space contamination).
_NEUTRAL_SENTENCES = [
    "This section is reserved for supplementary operational context.",
    "Standard observability pipelines are configured per the platform baseline.",
    "Routine housekeeping tasks run on the usual maintenance schedule.",
    "No additional advisories apply to the current diagnostic window.",
    "The deployment topology follows the documented reference architecture.",
    "Telemetry collection intervals match the default platform configuration.",
    "General runbook conventions are described in the platform handbook.",
    "Capacity headroom is reviewed on the regular operational cadence.",
    "Backup verification jobs complete within their nominal time budget.",
    "Configuration drift checks run according to the established policy.",
]


class ArmAssembler:
    """Assemble per-arm context strings from a fully-built (system="B") RCAContext."""

    def __init__(self, t_block: int):
        self.t_block = t_block

    # ── token helpers ──

    @staticmethod
    def _approx_tokens(s: str) -> int:
        return len(s) // 4

    def _fit_block(self, text: str, t_block: int) -> str:
        """Fit text to exactly ~t_block tokens (4*t_block chars) by truncate or pad."""
        target_chars = 4 * t_block
        text = text or ""
        if len(text) > target_chars:
            return text[:target_chars].rstrip() + " [truncated]"
        # pad with neutral boilerplate to reach the budget
        if len(text) < target_chars:
            pad_needed = target_chars - len(text)
            pad = self._make_filler(pad_needed)
            return text + "\n[padding] " + pad
        return text

    def _make_filler(self, n_chars: int) -> str:
        """Build neutral filler of ~n_chars from shuffled-but-deterministic sentences."""
        out = []
        total = 0
        i = 0
        while total < n_chars:
            s = _NEUTRAL_SENTENCES[i % len(_NEUTRAL_SENTENCES)]
            out.append(s)
            total += len(s) + 1
            i += 1
        return " ".join(out)[:n_chars]

    def _make_placebo(self, t_block: int) -> str:
        """Meaningless boilerplate filler block of ~t_block tokens (no real diff)."""
        body = self._make_filler(4 * t_block)
        return f"## Supplementary Notes\n{body}"

    # ── assembly ──

    def assemble(self, ctx, arm: str) -> str:
        """Return the context string for the given arm.

        All blocks are inserted after the obs block in the same position/order
        across arms (Lost-in-the-Middle control).
        """
        obs = ctx.to_system_a_context()

        gitops_text = "\n\n".join(
            p for p in (ctx.gitops_status, ctx.git_changes) if p
        )
        rag_text = ctx.rag_context or ""

        if arm == "C1_A":
            return obs
        if arm == "C2_gitops":
            block = self._fit_block(gitops_text, self.t_block)
            return f"{obs}\n\n## GitOps Status (FluxCD/ArgoCD)\n{block}"
        if arm == "C3_rag":
            block = self._fit_block(rag_text, self.t_block)
            return f"{obs}\n\n## Knowledge Base (RAG Retrieved)\n{block}"
        if arm == "C4_both":
            g = self._fit_block(gitops_text, self.t_block)
            r = self._fit_block(rag_text, self.t_block)
            return (
                f"{obs}\n\n## GitOps Status (FluxCD/ArgoCD)\n{g}"
                f"\n\n## Knowledge Base (RAG Retrieved)\n{r}"
            )
        if arm == "C5_placebo":
            placebo = self._make_placebo(2 * self.t_block)
            return f"{obs}\n\n{placebo}"
        raise ValueError(f"Unknown arm: {arm}")

    # ── confound check ──

    @staticmethod
    def _words(text: str) -> set:
        return {w for w in re.findall(r"[A-Za-z0-9_]+", (text or "").lower()) if len(w) > 3}

    def gitops_rag_jaccard(self, ctx) -> float:
        """Token (word) Jaccard between GitOps text and RAG text (words >3 chars)."""
        gitops_text = "\n\n".join(
            p for p in (ctx.gitops_status, ctx.git_changes) if p
        )
        a = self._words(gitops_text)
        b = self._words(ctx.rag_context or "")
        if not a and not b:
            return 0.0
        inter = len(a & b)
        union = len(a | b)
        return round(inter / union, 4) if union else 0.0
