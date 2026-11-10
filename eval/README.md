# LostLink evaluation harness

Ranks found items for each lost report with the production `BlendedScorer`
(`backend/pipeline/impl/scorer.py`) and reports, per weight variant (text-only,
text+location, text+location+time):

- **Ranking:** Hit@1, Recall@5, MRR over lost reports that have a true match.
- **Notifications at a threshold:** alert precision, false-alert rate (share of
  no-match reports that alerted), missed-notification rate.

## Datasets

| Dataset | Size | Use |
|---|---|---|
| `data/sample_dataset.json` | 4 lost / 4 found, hand-made 3-D vectors | Smoke test only. Perfect scores here say nothing about accuracy. |
| `benchmark.py` (built, then embedded) | 100 lost / 200 found | Main evaluation. |
| `benchmark.py`, `EVAL_SIZE=small` | 20 lost / 40 found | Seeded subset of the same items. Noisy: Hit@1 swings by up to ±0.3 between seeds, so prefer the full set for conclusions. |
| `generate.py` default / `GENERATE_SOURCE=seed` | up to 35 lost / 50 found | Older generated set; true pairs always share a zone and day, so it flatters location/time. |

The benchmark has 60 true pairs, each with a same-kind **hard negative** (e.g. the same
wallet without the red stripe), 20 near-miss and 20 unrelated lost reports with no true
match, and 80 assorted found items. It uses map coordinates (the production location
path), not zones. How often a true pair is found at the same place / nearby / far, and
how long after, are **assumptions** set at the top of `benchmark.py` and saved in the
dataset's `meta`; location and time results depend on them, so report them.

`EVAL_CONDITIONS=best_case` removes the look-alikes and puts every true pair at the
stated place within hours, like the 4x4 sample. It is an upper bound, not an estimate of
real-world accuracy; label it as such wherever it is reported.

## Run

```bash
cd eval
python3 -m pytest -q                                   # unit + structure tests (offline)

# Build the benchmark and embed it, then score it.
# Titan, as in production (needs AWS credentials + boto3):
GENERATE_SOURCE=benchmark EMBEDDER=titan EVAL_OUT=data/generated/benchmark_titan.json python3 generate.py
# or bge-m3 via the local stack's OpenAI-compatible endpoint (docs/LOCAL.md):
LLM_BASE_URL=... LLM_API_KEY=... LLM_EMBED_MODEL=bge-m3 \
  GENERATE_SOURCE=benchmark EMBEDDER=openai EVAL_OUT=data/generated/benchmark_bge-m3.json python3 generate.py

# Smaller 20 x 40 sets: add EVAL_SIZE=small, and EVAL_CONDITIONS=best_case for the upper bound.

python3 run_eval.py data/generated/benchmark_bge-m3.json
MATCH_THRESHOLD=0.7 python3 run_eval.py data/generated/benchmark_bge-m3.json    # other thresholds
```

Scores are not comparable across embedding models: re-tune the threshold per model.
Generated datasets and `output/` are git-ignored.
