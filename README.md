# Ghost Data Still Exists — Deletion Audit Agent

This repository contains the runnable evidence-driven solution, the complete participant-facing dataset in `dataset/`, and generated HackerRank deliverables. The dataset corpus is committed here for reproducibility and is excluded from the submission `code.zip`.

See `code/README.md` for the agent design and run instructions. GitHub Actions generates `output.csv` for all 518 requests, evaluates against the public sample, writes evaluation and usage reports, and publishes `code.zip` and a per-request `agent-traces.zip` as workflow artifacts.
