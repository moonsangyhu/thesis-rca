"""Check the reviewed static ontology; it deliberately never materializes data."""
from __future__ import annotations

import argparse
from pathlib import Path

try:
    from .scorer import InvalidInput, load_ontology
except ImportError:  # Direct script execution from the repository root.
    from scorer import InvalidInput, load_ontology


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
