# Token and cost usage report

## Final full-dataset run

- Model provider: None; deterministic local evidence parser, with no hosted model calls.
- Model name: None.
- Model calls: 0.
- Input tokens: 0.
- Output tokens: 0.
- Total tokens: 0.
- Average tokens per request: 0 across 518 requests.
- Estimated model cost: $0.00 total; $0.00 per request.

The full run reads participant-facing CSV files and the evidence corpus from the upstream dataset directory, extracts evidence from structured text, SQL, PDF, and image files, and writes output.csv. OCR dependencies are installed by GitHub Actions. No API key or external model service is required.

## Run totals

- Requests processed: 518
- Output status counts: COMPLETE=108, INCOMPLETE=406, NOT_APPLICABLE=4
- Per-model totals: not applicable (no models used).
- Overall totals: 0 calls, 0 input tokens, 0 output tokens, 0 tokens, $0.00 estimated cost.
