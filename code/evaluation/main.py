#!/usr/bin/env python3
"""Public-sample evaluation and usage reporting for the deletion audit agent."""
from __future__ import annotations
import argparse, csv, json, shutil, tempfile, sys
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import main as agent
FIELDS = ("step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id")

def read_rows(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def parsed_steps(row):
    try:
        data = json.loads(row.get("steps_json", "[]"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []

def build_sample_dataset(dataset, root):
    sample_dir = root / "dataset"
    sample_dir.mkdir(parents=True, exist_ok=True)
    for name in ("user_identities.csv", "user_audit_log.csv", "system_activity.csv", "deletion_rules.csv", "evidence_files.csv"):
        shutil.copy2(dataset / name, sample_dir / name)
    shutil.copy2(dataset / "sample_deletion_requests.csv", sample_dir / "deletion_requests.csv")
    shutil.copytree(dataset / "evidence", sample_dir / "evidence", dirs_exist_ok=True)
    return sample_dir

def evaluate(dataset, predictions):
    with tempfile.TemporaryDirectory(prefix="ghost-audit-eval-") as tmp:
        sample_dir = build_sample_dataset(dataset, Path(tmp))
        sample_prediction = Path(tmp) / "sample_predictions.csv"
        agent.run(sample_dir, sample_prediction)
        expected_rows = read_rows(dataset / "sample_output.csv")
        actual_rows = read_rows(sample_prediction)
    expected = {r["case_id"]: r for r in expected_rows}
    actual = {r["case_id"]: r for r in actual_rows}
    ids = sorted(set(expected) | set(actual))
    status_correct = sum(1 for cid in ids if cid in expected and cid in actual and expected[cid]["deletion_status"] == actual[cid]["deletion_status"])
    sequence_correct = 0
    fields_correct = 0
    fields_total = 0
    steps_expected_total = 0
    steps_exact = 0
    failures = []
    for cid in ids:
        er, ar = expected.get(cid, {}), actual.get(cid, {})
        es, ass = parsed_steps(er), parsed_steps(ar)
        if cid in expected and cid in actual and es == ass:
            sequence_correct += 1
        n = max(len(es), len(ass))
        steps_expected_total += len(es)
        for i in range(n):
            if i < len(es) and i < len(ass):
                steps_exact += int(es[i] == ass[i])
                fields_correct += sum(1 for f in FIELDS if es[i].get(f) == ass[i].get(f))
            fields_total += len(FIELDS)
        if (cid in expected and cid in actual and er.get("deletion_status") != ar.get("deletion_status")) or es != ass:
            if len(failures) < 12:
                failures.append(f"- {cid}: expected {er.get('deletion_status')} with {len(es)} steps; predicted {ar.get('deletion_status')} with {len(ass)} steps.")
    ncases = max(1, len(ids))
    status_accuracy = status_correct / ncases
    sequence_accuracy = sequence_correct / ncases
    row_accuracy = sum(1 for cid in ids if cid in expected and cid in actual and expected[cid]["deletion_status"] == actual[cid]["deletion_status"] and parsed_steps(expected[cid]) == parsed_steps(actual[cid])) / ncases
    step_accuracy = steps_exact / max(1, max(steps_expected_total, sum(len(parsed_steps(r)) for r in actual.values())))
    field_accuracy = fields_correct / max(1, fields_total)
    custom = [
        ("affirmative English erasure", "Please permanently erase my account and personal data.", True),
        ("affirmative Spanish deletion", "Solicito la eliminación permanente de mi cuenta.", True),
        ("affirmative French deletion", "Je demande la suppression définitive de mon compte.", True),
        ("export and marketing opt-out only", "Please export my data and opt me out of marketing.", False),
        ("profile correction only", "Please correct the email address on my profile.", False),
    ]
    custom_results = [(name, expected_value, agent.classify_request_text(prompt)) for name, prompt, expected_value in custom]
    custom_correct = sum(actual_value == expected_value for _, expected_value, actual_value in custom_results)
    dist = Counter(r["deletion_status"] for r in read_rows(predictions))
    report = [
        "# Evaluation report", "", "## Public sample validation", "",
        f"- Sample cases: {len(ids)}",
        f"- Case-level deletion-status accuracy: {status_correct}/{len(ids)} ({status_accuracy:.1%})",
        f"- Step-level exact accuracy: {steps_exact}/{max(steps_expected_total, sum(len(parsed_steps(r)) for r in actual.values()))} ({step_accuracy:.1%})",
        f"- Field-level accuracy across step fields: {fields_correct}/{fields_total} ({field_accuracy:.1%})",
        f"- Sequence accuracy (entire ordered steps_json): {sequence_correct}/{len(ids)} ({sequence_accuracy:.1%})",
        f"- Exact row accuracy (status and complete sequence): {row_accuracy:.1%}", "",
        "## Additional participant-created evaluation cases", "",
        "| Case | Expected deletion intent | Predicted | Result |", "|---|---:|---:|---|",
    ]
    for name, exp, got in custom_results:
        report.append(f"| {name} | {str(exp).lower()} | {str(got).lower()} | {'PASS' if exp == got else 'FAIL'} |")
    report += ["", f"Custom intent cases passed: {custom_correct}/{len(custom_results)}.", "", "## Failures found", ""]
    report += failures if failures else ["- No public-sample mismatches were observed."]
    report += ["", "## Public-sample case detail", ""]
    for cid in ids:
        er, ar = expected.get(cid, {}), actual.get(cid, {})
        es, ass = parsed_steps(er), parsed_steps(ar)
        if er.get("deletion_status") == ar.get("deletion_status") and es == ass:
            continue
        def sig(steps):
            return [(s.get("phase"), s.get("system_id"), s.get("resource_id"),
                     s.get("operation"), s.get("state"), s.get("evidence_id")) for s in steps]
        report.append(f"- {cid}: expected {er.get('deletion_status')} {json.dumps(sig(es), ensure_ascii=False)}; predicted {ar.get('deletion_status')} {json.dumps(sig(ass), ensure_ascii=False)}")
    report += [
        "", "## Improvements made", "",
        "- Added case-insensitive resolution across current and audited historical identifiers.",
        "- Applied the audit_at cutoff to evidence and identity-linked activity before assessing current state.",
        "- Read JSON snapshots, SQLite-compatible database captures, structured logs, PDFs, and screenshots.",
        "- Separated evidence findings from proposed remediation and future verification, and enforced required phase and operation ordering.",
        "- Kept NOT_APPLICABLE cases empty and used supplied retention categories to preserve retained records.",
        "", "## Full-dataset run", "",
        f"- Prediction rows: {sum(dist.values())}",
        f"- Status distribution: {', '.join(f'{k}={v}' for k, v in sorted(dist.items()))}",
        "- Hidden evaluation labels are not available; accuracy above is the public sample comparison only.",
    ]
    usage = [
        "# Token and cost usage report", "", "## Final full-dataset run", "",
        "- Model provider: None; deterministic local evidence parser, with no hosted model calls.",
        "- Model name: None.", "- Model calls: 0.", "- Input tokens: 0.", "- Output tokens: 0.",
        "- Total tokens: 0.", f"- Average tokens per request: 0 across {sum(dist.values())} requests.",
        "- Estimated model cost: $0.00 total; $0.00 per request.", "",
        "The full run reads participant-facing CSV files and the evidence corpus from the upstream dataset directory, extracts evidence from structured text, SQL, PDF, and image files, and writes output.csv. OCR dependencies are installed by GitHub Actions. No API key or external model service is required.",
        "", "## Run totals", "", f"- Requests processed: {sum(dist.values())}",
        f"- Output status counts: {', '.join(f'{k}={v}' for k, v in sorted(dist.items()))}",
        "- Per-model totals: not applicable (no models used).",
        "- Overall totals: 0 calls, 0 input tokens, 0 output tokens, 0 tokens, $0.00 estimated cost.",
    ]
    return "\n".join(report) + "\n", "\n".join(usage) + "\n"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--predictions", type=Path, required=True)
    p.add_argument("--report", type=Path, default=Path("code/evaluation/evaluation_report.md"))
    p.add_argument("--usage", type=Path, default=Path("code/evaluation/usage_report.md"))
    args = p.parse_args()
    report, usage = evaluate(args.dataset, args.predictions)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.usage.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")
    args.usage.write_text(usage, encoding="utf-8")
    print(report)
    print(usage)

if __name__ == "__main__":
    main()
