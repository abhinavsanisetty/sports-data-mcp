# Eval Harness

The harness in `harness.py` runs seed questions against a server implementation and scores each result. When the full NL eval is wired in Phase 6, Gemini calls will use `temperature=0` — this is a deliberate reproducibility setting per §3.16 of the design plan, chosen to make nightly eval results deterministic and comparable across runs, not a production recommendation (real query routing benefits from non-zero temperature for diverse phrasing).
