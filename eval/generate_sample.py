"""Build a 25 lost / 25 found evaluation dataset: LLM-written text, NUS places and times.

The descriptions are written by Qwen 3.6 35B on NUS SoClaaS (model alias "default") from
the prompts below. Places and times are set by fixed rules (see build()), including true
pairs found at another place or days later, so location and time can help or hurt. Every
description is embedded with bge-m3 on SoClaaS; vectors are cached, so a re-run only
embeds new text.

    set -a; . ../.env; set +a      # SOCLAAS_BASE_URL, SOCLAAS_API_KEY
    python3 generate_sample.py

Writes data/sample_dataset_qwen.json (committed, no vectors; its descriptions are reused if
it exists, delete it to generate new text) and data/generated/sample_dataset_qwen.json
(with vectors, for run_eval.py).
"""

import json
import os
import random
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
TEXT_OUT = os.path.join(HERE, "data", "sample_dataset_qwen.json")
EMBED_OUT = os.path.join(HERE, "data", "generated", "sample_dataset_qwen.json")
EMBED_CACHE = os.path.join(HERE, "data", "generated", "embeddings_bge-m3.json")
CHAT_MODEL = os.environ.get("SOCLAAS_MODEL", "default")  # Qwen 3.6 35B on SoClaaS
EMBED_MODEL = "bge-m3"
TEMPERATURE = 0.7
N_PAIRS, N_NO_MATCH, N_DISTRACTORS = 20, 5, 5  # 25 lost / 25 found, laid out like the 4x4 sample
# (name, latitude, longitude): real NUS places, approximate to ~100 m.
PLACES = [
    ("NUS Central Library", 1.2966, 103.7723), ("COM1, School of Computing", 1.2950, 103.7737),
    ("UTown Stephen Riady Centre", 1.3046, 103.7725), ("The Deck, Arts canteen", 1.2944, 103.7725),
    ("University Sports Centre", 1.2996, 103.7756), ("Engineering Block E1", 1.2988, 103.7711),
    ("Kent Ridge Bus Terminal", 1.2946, 103.7696), ("Kent Ridge MRT", 1.2935, 103.7846),
]
# How each of the 20 true pairs is found (see build()).
PAIR_CASES = ["typical"] * 12 + ["found_elsewhere"] * 4 + ["found_late"] * 4
PLACEMENT = ("12 true pairs are found at the place where they were lost, 1-12 h later; 4 are found at "
             "another NUS place 1-12 h later; 4 are found at the same place 2-7 days later. Unmatched lost "
             "reports and found items get a random place and day in Sep 2026. Seed 5224.")

SYSTEM = ("You write realistic test data for LostLink, a lost-and-found service on the National "
          "University of Singapore (NUS) campus. Reply with a JSON array only, without any other text.")

PAIRS_PROMPT = """Write {n} pairs of descriptions of everyday objects that students or staff lose on campus, one pair per object. Use {n} different objects and vary the kind of object widely. Describe only the object itself, never where or when it was lost or found.
- "lost": what the owner types when reporting it lost, from memory: 8 to 18 words with 2 to 4 details such as colour, brand, marks or contents.
- "found": what a staff member types after finding the same object: the same details in their own words, possibly leaving one out, 6 to 15 words, never "my".

Return a JSON array of {n} objects with the keys "lost" and "found"."""

NO_MATCH_PROMPT = """Here are descriptions of objects waiting at a lost-and-found office:
{found}

Write {n} lost reports for other objects, which nobody has found. Each is typed by the owner from memory, 8 to 18 words, and describes only the object, never where or when it was lost. None may describe any object above. About half should be the same kind of object as one above but clearly a different one (another colour, brand or mark); the rest should be other kinds of objects.

Return a JSON array of {n} strings."""

DISTRACTOR_PROMPT = """Here are lost reports from owners:
{lost}

Write {n} entries that staff typed for other objects handed in to the lost-and-found office, which nobody has reported lost. Each describes only the object as a stranger sees it, 6 to 15 words, never "my", and never where or when it was found. None may describe any object above. About half should be the same kind of object as one above but clearly a different one (another colour, brand or mark); the rest should be other kinds of objects.

Return a JSON array of {n} strings."""


def api(path: str, payload: dict) -> dict:
    request = Request(os.environ["SOCLAAS_BASE_URL"].rstrip("/") + path, data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json",
                               "Authorization": f"Bearer {os.environ['SOCLAAS_API_KEY']}"})
    for attempt in range(3):  # the gateway sometimes answers 502
        try:
            with urlopen(request, timeout=300) as response:
                return json.loads(response.read())
        except HTTPError as e:
            if e.code < 500 or attempt == 2:
                raise
            time.sleep(5)


def bullets(items) -> str:
    return "\n".join(f"- {x}" for x in items) or "- (none yet)"


def ask(prompt: str, n: int, calls: list, seen: set) -> list:
    """One chat call for n items. Items whose text is already in the dataset are dropped;
    if fewer than n remain, the whole call is retried (up to 3 times)."""
    for _ in range(3):
        reply = api("/chat/completions", {"model": CHAT_MODEL, "temperature": TEMPERATURE, "messages": [
            {"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]})
        text = reply["choices"][0]["message"]["content"]
        calls.append({"model": reply.get("model", CHAT_MODEL), "prompt": prompt})
        items, keys_used = [], set()
        for item in json.loads(text[text.find("["):text.rfind("]") + 1]):
            texts = [item.get("lost"), item.get("found")] if isinstance(item, dict) else [item]
            keys = [str(t or "").strip().lower() for t in texts]
            if all(keys) and len(set(keys)) == len(keys) and not (seen | keys_used).intersection(keys):
                keys_used.update(keys)
                items.append(item)
        if len(items) >= n:
            seen.update(keys_used)
            return items[:n]
        print(f"  got {len(items)} usable items of {n}; asking again")
    raise SystemExit("The model did not return enough usable items; run again.")


def generate_text() -> tuple[dict, tuple]:
    """Ask the LLM for the descriptions. Returns (meta with prompts, (pairs, no_match, distractors))."""
    calls: list = []
    seen: set = set()
    pairs = ask(PAIRS_PROMPT.format(n=N_PAIRS), N_PAIRS, calls, seen)
    print(f"  {len(pairs)} pairs")
    no_match = ask(NO_MATCH_PROMPT.format(n=N_NO_MATCH, found=bullets(p["found"] for p in pairs)),
                   N_NO_MATCH, calls, seen)
    print(f"  {len(no_match)} lost reports with no match")
    distractors = ask(DISTRACTOR_PROMPT.format(n=N_DISTRACTORS, lost=bullets([p["lost"] for p in pairs] + no_match)),
                      N_DISTRACTORS, calls, seen)
    print(f"  {len(distractors)} found items with no match")

    meta = {
        "descriptions_by": sorted({c["model"] for c in calls}),
        "via": "NUS SoClaaS (OpenAI-compatible API), model alias " + repr(CHAT_MODEL),
        "generated_at": iso(datetime.now(timezone.utc)), "temperature": TEMPERATURE,
        "prompts": {"system": SYSTEM, "pairs": PAIRS_PROMPT, "no_match": NO_MATCH_PROMPT,
                    "distractors": DISTRACTOR_PROMPT},
        "calls": calls,
    }
    return meta, (pairs, no_match, distractors)


def iso(t: datetime) -> str:
    return t.replace(microsecond=0).isoformat()


def build(pairs: list, no_match: list, distractors: list) -> tuple[list, list]:
    """Give every item a place and a time (PLACEMENT describes the rules)."""
    rng = random.Random(5224)
    start = datetime(2026, 9, 1, 8, tzinfo=timezone.utc)
    when = lambda: start + timedelta(days=rng.randrange(30), hours=rng.uniform(0, 12))  # noqa: E731
    loc = lambda p: {"name": p[0], "latitude": p[1], "longitude": p[2]}  # noqa: E731
    lost, found = [], []
    for i, (p, case) in enumerate(zip(pairs, PAIR_CASES), 1):
        place, t = rng.choice(PLACES), when()
        found_at = rng.choice([q for q in PLACES if q != place]) if case == "found_elsewhere" else place
        hours_later = rng.uniform(48, 168) if case == "found_late" else rng.uniform(1, 12)
        lost.append({"id": f"l-{i:02d}", "description": p["lost"], "location": loc(place),
                     "eventTime": iso(t), "truth": f"f-{i:02d}", "case": case})
        found.append({"id": f"f-{i:02d}", "description": p["found"], "location": loc(found_at),
                      "eventTime": iso(t + timedelta(hours=hours_later))})
    for i, d in enumerate(no_match, 1):
        lost.append({"id": f"l-n{i:02d}", "description": d, "location": loc(rng.choice(PLACES)),
                     "eventTime": iso(when()), "truth": None})
    for i, d in enumerate(distractors, 1):
        found.append({"id": f"f-d{i:02d}", "description": d, "location": loc(rng.choice(PLACES)),
                      "eventTime": iso(when())})
    rng.shuffle(lost)  # so list order cannot break a score tie in the true item's favour
    rng.shuffle(found)
    return lost, found


def texts_from(ds: dict) -> tuple[list, list, list]:
    """The LLM-written descriptions in an existing dataset file, in their original order."""
    found = {f["id"]: f["description"] for f in ds["found"]}
    lost = sorted(ds["lost"], key=lambda r: r["id"])
    return ([{"lost": r["description"], "found": found[r["truth"]]} for r in lost if r["truth"]],
            [r["description"] for r in lost if not r["truth"]],
            [found[k] for k in sorted(found) if k.startswith("f-d")])


def embed(texts: list[str]) -> dict:
    """Vectors for texts, from the cache where possible; new ones are fetched and cached."""
    cache = {}
    if os.path.exists(EMBED_CACHE):
        with open(EMBED_CACHE) as f:
            cache = json.load(f)
    todo = [t for t in dict.fromkeys(texts) if t not in cache]
    for i in range(0, len(todo), 32):
        rows = api("/embeddings", {"model": EMBED_MODEL, "input": todo[i:i + 32]})["data"]
        for text, row in zip(todo[i:i + 32], sorted(rows, key=lambda r: r["index"])):
            cache[text] = row["embedding"]
    if todo:
        os.makedirs(os.path.dirname(EMBED_CACHE), exist_ok=True)
        with open(EMBED_CACHE, "w") as f:
            json.dump(cache, f)
    print(f"Embeddings ({EMBED_MODEL}): {len(todo)} fetched, {len(set(texts)) - len(todo)} from cache")
    return cache


def main():
    if os.path.exists(TEXT_OUT):
        print(f"Reusing the descriptions in {TEXT_OUT} (delete it to generate new ones).")
        with open(TEXT_OUT) as f:
            old = json.load(f)
        meta, texts = old["meta"], texts_from(old)
    else:
        print(f"Writing descriptions with {CHAT_MODEL} on SoClaaS...")
        meta, texts = generate_text()
    lost, found = build(*texts)
    meta.pop("zones_and_times", None)
    meta["places_and_times"] = PLACEMENT
    ds = {"meta": meta, "lost": lost, "found": found}
    with open(TEXT_OUT, "w") as f:
        json.dump(ds, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {TEXT_OUT}")

    vectors = embed([r["description"] for r in lost + found])
    embedded = {"meta": {**meta, "embed_model": EMBED_MODEL},
                "lost": [{**r, "vecText": vectors[r["description"]]} for r in lost],
                "found": [{**r, "vecText": vectors[r["description"]]} for r in found]}
    with open(EMBED_OUT, "w") as f:
        json.dump(embedded, f)
    print(f"Wrote {EMBED_OUT}")


if __name__ == "__main__":
    main()
