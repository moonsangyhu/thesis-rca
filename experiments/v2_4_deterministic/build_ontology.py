"""Check the reviewed static ontology; it deliberately never materializes data."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    _REPO = Path(__file__).resolve().parents[2]
    if not (_REPO / "AGENTS.md").is_file() or not (_REPO / ".git").exists() or any(parent.is_symlink() for parent in (_REPO, *_REPO.parents)):
        raise RuntimeError("UNTRUSTED_REPO_BOOTSTRAP")
    sys.path.insert(0, str(_REPO))
    from experiments.v2_4_deterministic.scorer import InvalidInput, load_ontology
else:
    from .scorer import InvalidInput, load_ontology


def check(path: Path) -> dict:
    ontology = load_ontology(path)
    return {"status": "ONTOLOGY_CHECK_PASS", "ontology_version": ontology["ontology_version"], "incident_count": len(ontology["incidents"])}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ontology", type=Path, default=Path(__file__).with_name("ontology_v1.json"))
    args = parser.parse_args(argv)
    try:
        result = check(args.ontology)
    except InvalidInput as exc:
        raise SystemExit(str(exc)) from exc
    print(" ".join(f"{key}={value}" for key, value in sorted(result.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
