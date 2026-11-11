# LostLink evaluation

Scores every lost report against every found item with the production `BlendedScorer`
(`backend/pipeline/impl/scorer.py`) under four configurations: text only, text + location,
text + time, and text + location + time. Each uses the production weights (0.6 text, 0.25
location, 0.15 time) with the other components switched off; the scorer divides by the
weights it uses, so they are renormalized. Production code and its 0.7 default threshold are
not changed.

For every configuration and threshold (0.40 to 0.95 in steps of 0.05) it reports:

- **Hit@1, Recall@5, MRR** over lost reports that have a true match. The worker only stores
  matches at or above the threshold, so a true match below it counts as not found.
- **Alert precision**: share of alerts (scores at or above the threshold) that are the true match.
- **True-match recall**: share of true matches that alert.
- **Incorrect alerts**: number of alerts that are not the true match.
- **False-alert rate**: share of lost reports with no true match that still get an alert.

## Dataset

`data/sample_dataset_qwen.json`: 25 lost reports and 25 found items. 20 lost reports have one
true found item, 5 lost reports have no match, and 5 found items match nothing; several of the
unmatched items are close variants of real ones (another colour, brand or mark). Every
description was written by Qwen 3.6 35B on NUS SoClaaS; the prompts and every call are saved in
the file's `meta`. Places are real NUS locations and times are in September 2026:

- 12 true pairs are found where they were lost, 1 to 12 hours later;
- 4 are found at another NUS place, 1 to 12 hours later (location works against these);
- 4 are found at the same place 2 to 7 days later (time works against these);
- unmatched items get a random place and day.

`data/sample_dataset.json` is the original hand-made 4 x 4 smoke test used by the unit tests.

## Run

```bash
cd eval
set -a; . ../.env; set +a          # SOCLAAS_BASE_URL, SOCLAAS_API_KEY
python3 generate_sample.py          # places the committed descriptions and embeds them with bge-m3
python3 run_eval.py data/generated/sample_dataset_qwen.json
python3 -m pytest -q                # offline tests
```

`run_eval.py` writes `output/metrics.csv` (every configuration and threshold) and
`output/precision_recall.png`. Embeddings are cached in `data/generated/embeddings_bge-m3.json`,
so re-running `generate_sample.py` only calls the API for new text. To write new
descriptions, delete `data/sample_dataset_qwen.json` and run it again; the LLM gives different
text each time.

Scores depend on the embedding model: thresholds read off bge-m3 do not carry over to Titan,
which the AWS deployment uses.
