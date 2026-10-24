# Evaluation report

## Public sample validation

- Sample cases: 32
- Case-level deletion-status accuracy: 0/32 (0.0%)
- Step-level exact accuracy: 0/193 (0.0%)
- Field-level accuracy across step fields: 0/1351 (0.0%)
- Sequence accuracy (entire ordered steps_json): 0/32 (0.0%)
- Exact row accuracy (status and complete sequence): 0.0%

## Additional participant-created evaluation cases

| Case | Expected deletion intent | Predicted | Result |
|---|---:|---:|---|
| affirmative English erasure | true | false | FAIL |
| affirmative Spanish deletion | true | false | FAIL |
| affirmative French deletion | true | false | FAIL |
| export and marketing opt-out only | false | false | PASS |
| profile correction only | false | false | PASS |

Custom intent cases passed: 2/5.

## Failures found

- case_01: expected COMPLETE with 1 steps; predicted NOT_APPLICABLE with 0 steps.
- case_02: expected COMPLETE with 1 steps; predicted NOT_APPLICABLE with 0 steps.
- case_03: expected COMPLETE with 3 steps; predicted NOT_APPLICABLE with 0 steps.
- case_04: expected COMPLETE with 2 steps; predicted NOT_APPLICABLE with 0 steps.
- case_05: expected INCOMPLETE with 3 steps; predicted NOT_APPLICABLE with 0 steps.
- case_06: expected INCOMPLETE with 4 steps; predicted NOT_APPLICABLE with 0 steps.
- case_07: expected INCOMPLETE with 4 steps; predicted NOT_APPLICABLE with 0 steps.
- case_08: expected INCOMPLETE with 4 steps; predicted NOT_APPLICABLE with 0 steps.
- case_09: expected INCOMPLETE with 5 steps; predicted NOT_APPLICABLE with 0 steps.
- case_10: expected INCOMPLETE with 4 steps; predicted NOT_APPLICABLE with 0 steps.
- case_11: expected INCOMPLETE with 14 steps; predicted NOT_APPLICABLE with 0 steps.
- case_12: expected INCOMPLETE with 5 steps; predicted NOT_APPLICABLE with 0 steps.

## Improvements made

- Added case-insensitive resolution across current and audited historical identifiers.
- Applied the audit_at cutoff to evidence and identity-linked activity before assessing current state.
- Read JSON snapshots, SQLite-compatible database captures, structured logs, PDFs, and screenshots.
- Separated evidence findings from proposed remediation and future verification, and enforced required phase and operation ordering.
- Kept NOT_APPLICABLE cases empty and used supplied retention categories to preserve retained records.

## Full-dataset run

- Prediction rows: 518
- Status distribution: NOT_APPLICABLE=518
- Hidden evaluation labels are not available; accuracy above is the public sample comparison only.
