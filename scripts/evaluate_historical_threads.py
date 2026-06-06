#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.operator.historical_thread_evaluator import get_historical_thread_evaluator


def collect_thread_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(
        file_path
        for file_path in path.rglob("*")
        if file_path.is_file() and file_path.suffix.lower() in {".txt", ".md"}
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate historical guest messaging threads for workflow/detector review.")
    parser.add_argument("input", help="Text file or directory containing historical thread text files")
    parser.add_argument("--output-dir", default="scripts/output/historical_thread_evaluation", help="Directory for evaluation artifacts")
    args = parser.parse_args()

    evaluator = get_historical_thread_evaluator()
    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    analyses = []
    for thread_file in collect_thread_files(input_path):
        text = thread_file.read_text(encoding="utf-8", errors="ignore")
        analysis = evaluator.analyze_text(text, source_name=thread_file.name)
        review_template = evaluator.build_review_template(analysis)

        base_name = thread_file.stem
        (output_dir / f"{base_name}.analysis.json").write_text(json.dumps(analysis, indent=2), encoding="utf-8")
        (output_dir / f"{base_name}.review-template.json").write_text(json.dumps(review_template, indent=2), encoding="utf-8")
        analyses.append(
            {
                "source_name": analysis["source_name"],
                "parse_mode": analysis["parse_mode"],
                "turn_count": analysis["turn_count"],
                "qa_pair_count": analysis["qa_pair_count"],
                "domain_counts": analysis["domain_counts"],
            }
        )

    summary = {
        "input": str(input_path),
        "thread_count": len(analyses),
        "threads": analyses,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
