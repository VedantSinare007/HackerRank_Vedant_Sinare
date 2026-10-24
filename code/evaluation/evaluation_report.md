# Evaluation report

## Public sample validation

- Sample cases: 32
- Case-level deletion-status accuracy: 22/32 (68.8%)
- Step-level exact accuracy: 65/193 (33.7%)
- Field-level accuracy across step fields: 756/1456 (51.9%)
- Sequence accuracy (entire ordered steps_json): 5/32 (15.6%)
- Exact row accuracy (status and complete sequence): 15.6%

## Additional participant-created evaluation cases

| Case | Expected deletion intent | Predicted | Result |
|---|---:|---:|---|
| affirmative English erasure | true | true | PASS |
| affirmative Spanish deletion | true | true | PASS |
| affirmative French deletion | true | true | PASS |
| export and marketing opt-out only | false | false | PASS |
| profile correction only | false | false | PASS |

Custom intent cases passed: 5/5.

## Failures found

- case_01: expected COMPLETE with 1 steps; predicted COMPLETE with 0 steps.
- case_02: expected COMPLETE with 1 steps; predicted COMPLETE with 0 steps.
- case_03: expected COMPLETE with 3 steps; predicted INCOMPLETE with 4 steps.
- case_04: expected COMPLETE with 2 steps; predicted COMPLETE with 0 steps.
- case_06: expected INCOMPLETE with 4 steps; predicted INCOMPLETE with 6 steps.
- case_07: expected INCOMPLETE with 4 steps; predicted INCOMPLETE with 3 steps.
- case_08: expected INCOMPLETE with 4 steps; predicted INCOMPLETE with 3 steps.
- case_09: expected INCOMPLETE with 5 steps; predicted INCOMPLETE with 3 steps.
- case_10: expected INCOMPLETE with 4 steps; predicted COMPLETE with 0 steps.
- case_12: expected INCOMPLETE with 5 steps; predicted COMPLETE with 2 steps.
- case_15: expected INCOMPLETE with 5 steps; predicted COMPLETE with 1 steps.
- case_17: expected INCOMPLETE with 5 steps; predicted INCOMPLETE with 4 steps.

## Improvements made

- Added case-insensitive resolution across current and audited historical identifiers.
- Applied the audit_at cutoff to evidence and identity-linked activity before assessing current state.
- Read JSON snapshots, SQLite-compatible database captures, structured logs, PDFs, and screenshots.
- Separated evidence findings from proposed remediation and future verification, and enforced required phase and operation ordering.
- Kept NOT_APPLICABLE cases empty and used supplied retention categories to preserve retained records.

## Full-dataset run

- Prediction rows: 518
- Status distribution: COMPLETE=124, INCOMPLETE=390, NOT_APPLICABLE=4
- Hidden evaluation labels are not available; accuracy above is the public sample comparison only.
