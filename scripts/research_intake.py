#!/usr/bin/env python3
"""Create thesis-rca paper idea intake cards.

This script is intentionally dependency-free. It turns a promising daily paper
idea into a structured experiment-candidate card under docs/research_inbox.
It does not claim the idea is accepted; acceptance requires the gates in
rules/paper-idea-to-experiment.md.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = REPO_ROOT / "docs" / "templates" / "paper_idea_card.md"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "research_inbox" / "paper_ideas"
ALLOWED_STATUS = {
    "candidate",
    "needs-reading",
    "ready-for-experiment",
    "rejected-for-now",
}


def slugify(text: str, max_len: int = 72) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9가-힣]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if not text:
        return "untitled-paper-idea"
    return text[:max_len].strip("-") or "untitled-paper-idea"


def fill_template(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def unique_path(output_dir: Path, date_prefix: str, slug: str) -> Path:
    candidate = output_dir / f"{date_prefix}-{slug}.md"
    if not candidate.exists():
        return candidate
    for i in range(2, 100):
        candidate = output_dir / f"{date_prefix}-{slug}-{i}.md"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Too many duplicate files for slug: {slug}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a structured paper-idea card for thesis-rca experiments."
    )
    parser.add_argument("--title", required=True, help="Paper title or short idea name")
    parser.add_argument("--url", default="TBD", help="Paper URL / DOI / arXiv / repo")
    parser.add_argument(
        "--source",
        default="NotebookLM daily paper audio",
        help="Where the idea came from",
    )
    parser.add_argument(
        "--idea",
        required=True,
        help="The concrete idea to preserve for possible experiment use",
    )
    parser.add_argument(
        "--why",
        default="TBD",
        help="Why the user/advisor thinks this may matter for thesis-rca",
    )
    parser.add_argument(
        "--status",
        default="candidate",
        choices=sorted(ALLOWED_STATUS),
        help="Initial triage status",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory, relative to repo root or absolute",
    )
    parser.add_argument(
        "--template",
        default=str(DEFAULT_TEMPLATE),
        help="Template file, relative to repo root or absolute",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="YYYY-MM-DD. Defaults to local date.",
    )
    return parser.parse_args()


def resolve_path(path_text: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def main() -> int:
    args = parse_args()
    template_path = resolve_path(args.template)
    output_dir = resolve_path(args.output_dir)

    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    created_date = args.date or dt.datetime.now().strftime("%Y-%m-%d")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", created_date):
        raise ValueError("--date must be YYYY-MM-DD")

    slug = slugify(args.title)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = unique_path(output_dir, created_date, slug)

    values = {
        "title": args.title.strip(),
        "status": args.status,
        "created": created_date,
        "source": args.source.strip(),
        "url": args.url.strip() or "TBD",
        "idea": args.idea.strip(),
        "why": args.why.strip() or "TBD",
    }
    content = fill_template(template_path.read_text(encoding="utf-8"), values)
    output_path.write_text(content, encoding="utf-8")

    try:
        display_path = output_path.relative_to(REPO_ROOT)
    except ValueError:
        display_path = output_path
    print(f"created: {display_path}")
    print(f"status: {args.status}")
    print("next: read rules/paper-idea-to-experiment.md and decide whether to promote to docs/papers/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
