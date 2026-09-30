"""Ground-truth generation + embedding for the evaluation harness (needs Bedrock).

generate_dataset(): uses Claude (via the pipeline's model config) to synthesise lost/found
item descriptions with known pairings + distractors. Kept small to limit cost.
embed_dataset(): fills each record's vecText via Titan, so the offline harness can score.

Run once and cache to eval/data/generated/dataset.json; the metric sweep then runs pure.
"""

from __future__ import annotations

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import boto3

_REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "ap-southeast-2"))
_CLAUDE = os.environ.get("DESCRIBE_MODEL_ID", "au.anthropic.claude-haiku-4-5-20251001-v1:0")
_TITAN = os.environ.get("EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")

ZONES = ["zone-library", "zone-canteen", "zone-gym", "zone-bus-stop", "zone-lecture-hall"]


def _bedrock():
    return boto3.client("bedrock-runtime", region_name=_REGION)


def _claude_json(prompt: str, max_tokens: int = 1500) -> str:
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
    }
    resp = _bedrock().invoke_model(modelId=_CLAUDE, body=json.dumps(body))
    payload = json.loads(resp["body"].read())
    return "".join(b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text")


def _claude_pairs(n_pairs: int) -> list[dict]:
    prompt = (
        f"Generate {n_pairs} everyday objects people lose (wallets, bottles, umbrellas, "
        "electronics, bags, keys, jackets, etc.). For each, output a JSON object with: "
        '"category", "lost_desc" (how an owner would describe it from memory, ~1 sentence), '
        '"found_desc" (how staff would describe the same physical item, phrased '
        "differently but clearly the same object, ~1 sentence). Vary colours, brands, and "
        "distinctive marks. Return ONLY a JSON array, no prose."
    )
    return json.loads(_extract_json_array(_claude_json(prompt)))


def _claude_strings(n: int, kind: str) -> list[str]:
    prompt = (
        f"Generate {n} short, distinct descriptions of everyday {kind} objects "
        "(1 sentence each). Return ONLY a JSON array of strings."
    )
    return json.loads(_extract_json_array(_claude_json(prompt)))


def generate_dataset(n_pairs: int = 25, n_distractor_found: int = 25,
                     n_distractor_lost: int = 10) -> dict:
    """Generate a paired lost/found dataset with distractors on both sides.

    Source of descriptions:
      - GENERATE_SOURCE=claude (default): use Claude to synthesise descriptions. Falls
        back to the hand-authored seed if Anthropic access is not yet granted.
      - GENERATE_SOURCE=seed: use eval/seed_pairs.py directly (no Claude).
    Embeddings are always produced by Titan in embed_dataset().

    Scale up n_pairs~50, n_distractor_found~150 for the report's ~100 lost / ~200 found
    (seed source is capped by the hand-authored list sizes).
    """
    source = os.environ.get("GENERATE_SOURCE", "claude").lower()
    pairs, dfound, dlost = None, None, None

    if source != "seed":
        try:
            pairs = _claude_pairs(n_pairs)
            dfound = _claude_strings(n_distractor_found, "found")
            dlost = _claude_strings(n_distractor_lost, "unusual/specific lost")
        except Exception as e:  # noqa: BLE001 — e.g. Anthropic use-case form not submitted
            print(f"  Claude generation unavailable ({type(e).__name__}); using seed pairs.")

    if pairs is None:
        from seed_pairs import PAIRS, DISTRACTOR_FOUND, DISTRACTOR_LOST
        pairs = PAIRS
        dfound = DISTRACTOR_FOUND
        dlost = DISTRACTOR_LOST

    lost, found = [], []
    for i, p in enumerate(pairs[:n_pairs]):
        fid = f"f-{uuid.uuid4().hex[:8]}"
        zone = ZONES[i % len(ZONES)]
        found.append({"id": fid, "description": p["found_desc"], "locationZone": zone,
                      "eventTime": f"2026-09-{(i % 27) + 1:02d}T12:00:00+00:00"})
        lost.append({"id": f"l-{uuid.uuid4().hex[:8]}", "description": p["lost_desc"],
                     "locationZone": zone,
                     "eventTime": f"2026-09-{(i % 27) + 1:02d}T09:00:00+00:00", "truth": fid})

    for i, d in enumerate(dfound[:n_distractor_found]):
        found.append({"id": f"f-{uuid.uuid4().hex[:8]}", "description": d,
                      "locationZone": ZONES[i % len(ZONES)],
                      "eventTime": f"2026-09-{(i % 27) + 1:02d}T15:00:00+00:00"})

    for i, d in enumerate(dlost[:n_distractor_lost]):
        lost.append({"id": f"l-{uuid.uuid4().hex[:8]}", "description": d,
                     "locationZone": ZONES[i % len(ZONES)],
                     "eventTime": f"2026-09-{(i % 27) + 1:02d}T08:00:00+00:00", "truth": None})

    return {"lost": lost, "found": found}


def _extract_json_array(text: str) -> str:
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON array in model output: {text[:120]}")
    return text[start:end + 1]


def embed_dataset(dataset: dict) -> dict:
    """Fill vecText on every record via Titan. Mutates + returns the dataset."""
    brt = _bedrock()

    def embed(text: str) -> list[float]:
        resp = brt.invoke_model(modelId=_TITAN, body=json.dumps({"inputText": text}))
        return json.loads(resp["body"].read())["embedding"]

    for rec in dataset["lost"] + dataset["found"]:
        if not rec.get("vecText") and rec.get("description"):
            rec["vecText"] = embed(rec["description"])
    return dataset


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "data", "generated")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dataset.json")

    # Defaults are small to limit cost; override via env for the full ~100/200 set.
    n_pairs = int(os.environ.get("EVAL_PAIRS", "25"))
    n_df = int(os.environ.get("EVAL_DISTRACTOR_FOUND", "25"))
    n_dl = int(os.environ.get("EVAL_DISTRACTOR_LOST", "10"))

    print(f"Generating dataset ({n_pairs} pairs, {n_df} distractor-found, {n_dl} distractor-lost)...")
    ds = generate_dataset(n_pairs, n_df, n_dl)
    print(f"  lost={len(ds['lost'])} found={len(ds['found'])}; embedding via Titan...")
    ds = embed_dataset(ds)
    with open(out_path, "w") as f:
        json.dump(ds, f)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
