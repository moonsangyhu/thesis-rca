"""
LLM-based RCA inference module.

Usage:
    from src.llm import RCAEngine, RCAOutput
    engine = RCAEngine(model="claude-sonnet-4-6")
    result = engine.analyze(context_str, fault_id="F1", trial=1, system="A")
"""
from .rca_engine import RCAEngine, RCAOutput

__all__ = ["RCAEngine", "RCAOutput"]
