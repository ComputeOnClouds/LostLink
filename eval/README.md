# LostLink evaluation

Scores every lost report against every found item with the production `BlendedScorer`
(`backend/pipeline/impl/scorer.py`) under four configurations: text only, text + location,
text + time, and text + location + time. Each uses the production weights (0.6 text, 0.25
location, 0.15 time) with the other components switched off; the scorer divides by the
weights it uses, so they are renormalized. Production code and its 0.7 default threshold are
not changed.

Over the lost reports that have a true match, using the complete ranked list of candidates
(so these do not depend on the threshold):

- **Hit@1**: the true match is ranked first. **Recall@5**: it is in the top five.
  **MRR**: mean of 1 / rank of the true match.

At each threshold from 0.40 to 0.95 (steps of 0.05), where every candidate scoring at or
above the threshold is an alert:

- **Alert precision**: share of alerts that are the true match.
- **True-match notification recall** (`true_match_recall`): share of true matches that alert.
- **Incorrect alerts**: number of alerts that are not the true match.
- **False-alert rate**: share of lost reports with no true match that still get an alert.

## Dataset

`data/sample_dataset_qwen.json`: 25 lost and 25 found reports, built from 10 groups of three
look-alike objects (same kind and colour, often the same brand, such as three black wallets).
Qwen 3.6 35B on NUS SoClaaS wrote every description; owners' reports range from two words
("Black wallet") to a short sentence, and staff describe objects in their own words. The prompt,
the call and the model's output (`groups`) are saved in the file.

In each group two objects are true pairs and the third is a lost report nobody found
(groups 1-5) or a found item nobody reported (groups 6-10), so every lost report competes with
look-alikes. Places are real NUS locations and times are in September 2026, set by fixed rules
(`PLACEMENT` in `generate_sample.py`, also saved in the file):

- groups 1-4: the two pairs are lost on the same day at places at least 800 m apart, so
  location can tell them apart;
- groups 5-8: lost within 400 m of each other, 5 to 10 days apart, so time can tell them apart;
- groups 9-10: lost within 400 m of each other on the same day, so neither can;
- 14 pairs are found where they were lost, 1-12 h later; 3 are found at another place and 3 are
  found 2-7 days later, so location or time can also work against the true match.

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
