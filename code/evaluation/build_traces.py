#!/usr/bin/env python3
"""Build shareable, structured execution traces from the deterministic audit run."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def build(dataset: Path, predictions: Path, destination: Path) -> None:
    requests = {row["case_id"]: row for row in read_rows(dataset / "deletion_requests.csv")}
    outputs = read_rows(predictions)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="\n") as stream:
        for output in outputs:
            request = requests[output["case_id"]]
            steps = json.loads(output["steps_json"])
            trace = {
                "trace_version": "1.0",
                "case_id": output["case_id"],
                "request": {
                    "email": request.get("email", ""),
                    "requested_at": request.get("requested_at", ""),
                    "reported_status": request.get("reported_status", ""),
                    "reported_at": request.get("reported_at", ""),
                    "audit_at": request.get("audit_at", ""),
                    "request_text": request.get("request_text", ""),
                },
                "decision": {
                    "deletion_status": output["deletion_status"],
                    "step_count": len(steps),
                    "steps": steps,
                    "evidence_ids": sorted({step["evidence_id"] for step in steps if step.get("evidence_id")}),
                },
                "trace_note": "Observable deterministic retrieval and policy output; this record does not claim hidden model reasoning.",
            }
            stream.write(json.dumps(trace, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("dataset"))
    parser.add_argument("--predictions", type=Path, default=Path("output.csv"))
    parser.add_argument("--output", type=Path, default=Path("agent_traces.jsonl"))
    args = parser.parse_args()
    build(args.dataset, args.predictions, args.output)


if __name__ == "__main__":
    main()
