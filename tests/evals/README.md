# Eval Harness

The harness in `harness.py` runs seed questions against a server implementation and scores each result. Both the eval generator script (`scripts/generate_evals.py`) and the future NL eval (wired in Phase 6) use `temperature=0` — this is a deliberate reproducibility setting per §3.16 of the design plan, chosen to make generated questions and nightly eval results deterministic and comparable across runs, not a production recommendation (real query routing benefits from non-zero temperature for diverse phrasing).
