#!/usr/bin/env python3
"""Split workflow_output.json into one JSON file per dataset item.

NAT eval writes workflow_output.json with only the structured fields (id,
question, generated_answer, etc.) and does not include extra dataset fields
such as idx. This script merges idx (and id) from the original dataset by
default (--dataset points to the benchmark dataset by default).

Reads the combined workflow output and writes each record to
output_dir/items/<idx>.<ext> (or <id>.<ext> when idx is unavailable). By default
each file is a .md file containing only the generated_answer (report) text.
Use --keep-all-fields to write the full record as .json (id, idx, question,
generated_answer, etc.).

Usage:
 python split_workflow_output_to_per_item.py --input path/to/workflow_output.json --output-dir path/to/results/run_1
 python split_workflow_output_to_per_item.py --input workflow_output.json --output-dir results/run_1 --keep-all-fields
"""

import argparse
import json
import re
import sys
from pathlib import Path


def load_dataset_id_to_idx(dataset_path: Path) -> dict:
    """Load JSONL dataset and return mapping from item id to {idx, id} for merging."""
    out = {}
    with open(dataset_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            key = row.get("id")
            if key is not None:
                out[str(key)] = {"idx": row.get("idx"), "id": key}
    return out


def sanitize_filename(id_val) -> str:
    """Turn an id into a safe filename (no path separators or problematic chars)."""
    s = str(id_val).strip()
    s = re.sub(r"[^\w\-.]", "_", s)
    return s or "unknown"


def _default_dataset_path() -> Path:
    """Default path to the benchmark dataset (data/tasks_and_rubrics.jsonl next to script dir)."""
    return Path(__file__).resolve().parent.parent / "data" / "tasks_and_rubrics.jsonl"


def main():
    parser = argparse.ArgumentParser(
        description="Split workflow_output.json into one file per item (output_dir/items/<idx>.json or <id>.json)"
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to workflow_output.json",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory containing workflow_output.json; items will be written to <output-dir>/items/",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=_default_dataset_path(),
        help="Path to original dataset JSONL for merging idx/id",
    )
    parser.add_argument(
        "--keep-all-fields",
        action="store_true",
        help="Write the full record as JSON; default is a .md file with only the report text",
    )

    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print("Error: workflow_output.json should be a JSON array", file=sys.stderr)
        sys.exit(1)

    id_to_meta = {}
    if args.dataset and args.dataset.exists():
        id_to_meta = load_dataset_id_to_idx(args.dataset)

    items_dir = args.output_dir / "reports"
    items_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for record in data:
        id_val = record.get("id", written)
        meta = id_to_meta.get(str(id_val), {})
        idx_val = record.get("idx") if record.get("idx") is not None else meta.get("idx")
        if idx_val is not None:
            record["idx"] = idx_val
        if meta.get("id") is not None and record.get("id") is None:
            record["id"] = meta["id"]
        # Prefer idx for filename so filenames match dataset order and are stable
        if idx_val is not None:
            name = str(idx_val)
        else:
            name = sanitize_filename(id_val)
        if args.keep_all_fields:
            out_path = items_dir / f"{name}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2, default=str)
        else:
            out_path = items_dir / f"idx-{name}.md"
            content = record.get("generated_answer")
            if content is None:
                content = ""
            elif not isinstance(content, str):
                content = str(content)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(content)
        written += 1

    print(f"Wrote {written} item(s) to {items_dir}")


if __name__ == "__main__":
    main()
