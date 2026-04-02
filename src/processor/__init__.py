"""
Signal preprocessor for K8s RCA.

Transforms raw collected signals into structured context for LLM.

Usage:
    from src.processor import ContextBuilder, RCAContext
    builder = ContextBuilder()
    ctx = builder.build(signals, fault_id="F1", trial=1, system="B")
    print(ctx.to_context())
"""
from .context_builder import ContextBuilder, RCAContext

__all__ = ["ContextBuilder", "RCAContext"]
