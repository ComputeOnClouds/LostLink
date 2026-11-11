"""Build a 25 lost / 25 found evaluation dataset of look-alike objects, then embed it.

Qwen 3.6 35B on NUS SoClaaS (model alias "default") writes 10 groups of three look-alike
objects (same kind and colour, often the same brand), each with a short owner's report and
a short staff report. build() turns them into reports at real NUS places and times: in every
group two objects are true pairs and the third is either a lost report nobody found
(groups 1-5) or a found item nobody reported (groups 6-10). PLACEMENT states the rules.
Every description is embedded with bge-m3 on SoClaaS and the vectors are cached.

    set -a; . ../.env; set +a      # SOCLAAS_BASE_URL, SOCLAAS_API_KEY
    python3 generate_sample.py

Writes data/sample_dataset_qwen.json (committed, no vectors; the LLM's text in its "groups"
is reused if the file exists, delete it to generate new text) and
data/generated/sample_dataset_qwen.json (with vectors, for run_eval.py).
"""

import json
import math
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
N_GROUPS = 10  # x 3 objects: 20 true pairs, 5 unmatched lost reports, 5 unmatched found items

# (name, latitude, longitude): real NUS places, approximate to ~100 m.
PLACES = [
    ("NUS Central Library", 1.2966, 103.7723), ("COM1, School of Computing", 1.2950, 103.7737),
    ("UTown Stephen Riady Centre", 1.3046, 103.7725), ("The Deck, Arts canteen", 1.2944, 103.7725),
    ("University Sports Centre", 1.2996, 103.7756), ("Engineering Block E1", 1.2988, 103.7711),
    ("Kent Ridge Bus Terminal", 1.2946, 103.7696), ("Kent Ridge MRT", 1.2935, 103.7846),
]
NEAR_M, FAR_M = 400, 800
SCENARIOS = ["location"] * 4 + ["time"] * 4 + ["same"] * 2  # per group, see PLACEMENT
# (group index, object index) of the true pairs not found where and when they were lost. Both
# objects of a group take a turn, so these cases include detailed and very short reports.
FOUND_ELSEWHERE, FOUND_LATE = {(0, 1), (4, 0), (8, 1)}, {(1, 0), (5, 1), (9, 0)}
PLACEMENT = (
    "In each group the two true pairs are lost on the same day at places at least 800 m apart (groups 1-4: "
    "location separates them), at places within 400 m of each other 5-10 days apart (groups 5-8: time "
    "separates them), or within 400 m of each other on the same day (groups 9-10: neither does). Items are "
    "found where they were lost, 1-12 h later, except six pairs: object 2 of groups 1 and 9 and object 1 of "
    "group 5 are found at another place; object 1 of groups 2 and 10 and object 2 of group 6 are found at the "
    "same place 2-7 days later. The third object of a group is lost (groups 1-5) or found (groups 6-10) at the "
    "group's first place within 3 days in groups 1, 3, 5, 7 and 9, and at a random place and day in the "
    "others. Lost times are 09:00-18:00 in Sep 2026. Seed 5224.")

SYSTEM = ("You write realistic test data for LostLink, a lost-and-found service on the National "
          "University of Singapore (NUS) campus. Reply with a JSON array only, without any other text.")

GROUPS_PROMPT = """Write {n} groups of look-alike everyday objects that students and staff lose on a university campus, three objects per group. The three objects in a group are the same kind of object and look alike: the same colour, and often the same brand (for example three black umbrellas, or three white AirPods cases). They differ only in small details, such as a sticker, a scratch, a keychain or what is inside. Use a different kind of object for each group.

For each object write two reports. Describe only the object, never where or when it was lost or found.
- "lost": what the owner types when reporting it lost, from memory. Vary the length: about a third of the lost reports are very short, 2 to 4 words (like "black umbrella"); the rest are 6 to 15 words and mention one or two identifying details.
- "found": what a staff member types when the object is handed in, 3 to 12 words. Staff describe what they see, in their own words, and often use a generic name instead of the brand. About half the time they mention the same identifying detail as the owner (in different words); otherwise they mention a different detail or none. Never write "my".

Return a JSON array of {n} objects, each with the keys "kind" (a few words) and "objects" (an array of 3 objects with the keys "lost" and "found")."""


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


def iso(t: datetime) -> str:
    return t.replace(microsecond=0).isoformat()


def generate_groups() -> tuple[dict, list]:
    """One chat call for all groups, retried if the reply does not have the expected shape."""
    prompt, calls = GROUPS_PROMPT.format(n=N_GROUPS), []
    for _ in range(3):
        reply = api("/chat/completions", {"model": CHAT_MODEL, "temperature": TEMPERATURE, "messages": [
            {"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]})
        text = reply["choices"][0]["message"]["content"]
        calls.append({"model": reply.get("model", CHAT_MODEL), "prompt": prompt})
        try:
            groups = [{"kind": " ".join(g["kind"].split()),
                       "objects": [{k: " ".join(o[k].split()) for k in ("lost", "found")} for o in g["objects"]]}
                      for g in json.loads(text[text.find("["):text.rfind("]") + 1])]
            if (len(groups) == N_GROUPS and all(len(g["objects"]) == 3 for g in groups)
                    and all(o["lost"] and o["found"] for g in groups for o in g["objects"])
                    and len({g["kind"].lower() for g in groups}) == N_GROUPS):
                meta = {"descriptions_by": sorted({c["model"] for c in calls}),
                        "via": "NUS SoClaaS (OpenAI-compatible API), model alias " + repr(CHAT_MODEL),
                        "generated_at": iso(datetime.now(timezone.utc)), "temperature": TEMPERATURE,
                        "prompts": {"system": SYSTEM, "groups": GROUPS_PROMPT}, "calls": calls}
                return meta, groups
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
        print(f"  reply did not have {N_GROUPS} groups of 3 objects with both reports; asking again")
    raise SystemExit("The model did not return usable groups; run again.")


def distance_m(a: tuple, b: tuple) -> float:
    lat_a, lat_b = math.radians(a[1]), math.radians(b[1])
    h = (math.sin((lat_b - lat_a) / 2) ** 2
         + math.cos(lat_a) * math.cos(lat_b) * math.sin(math.radians(b[2] - a[2]) / 2) ** 2)
    return 2 * 6_371_008.8 * math.asin(math.sqrt(h))


def build(groups: list) -> tuple[list, list]:
    """Turn the LLM's groups into lost and found reports with places and times (see PLACEMENT)."""
    rng = random.Random(5224)
    start = datetime(2026, 9, 1, 9, tzinfo=timezone.utc)
    hours = lambda lo, hi: timedelta(hours=rng.uniform(lo, hi))  # noqa: E731
    days = lambda lo, hi: timedelta(days=rng.randint(lo, hi))  # noqa: E731
    loc = lambda p: {"name": p[0], "latitude": p[1], "longitude": p[2]}  # noqa: E731
    lost, found = [], []
    for g, group in enumerate(groups):
        first, second, extra = group["objects"]
        place_a, t_a = rng.choice(PLACES), start + days(0, 24) + hours(0, 9)  # daytime, 09:00-18:00
        if SCENARIOS[g] == "location":
            place_b, t_b = rng.choice([p for p in PLACES if distance_m(p, place_a) >= FAR_M]), t_a + hours(-3, 3)
        else:
            place_b = rng.choice([p for p in PLACES if distance_m(p, place_a) <= NEAR_M])
            t_b = t_a + (days(5, 10) if SCENARIOS[g] == "time" else timedelta()) + hours(-3, 3)
        for m, (obj, place, t) in enumerate([(first, place_a, t_a), (second, place_b, t_b)]):
            i, case, found_at, delay = 2 * g + m + 1, "typical", place, hours(1, 12)
            if (g, m) in FOUND_ELSEWHERE:
                case, found_at = "found_elsewhere", rng.choice([p for p in PLACES if p != place])
            if (g, m) in FOUND_LATE:
                case, delay = "found_late", hours(48, 168)
            lost.append({"id": f"l-{i:02d}", "group": g + 1, "description": obj["lost"], "location": loc(place),
                         "eventTime": iso(t), "truth": f"f-{i:02d}", "case": case})
            found.append({"id": f"f-{i:02d}", "group": g + 1, "description": obj["found"],
                          "location": loc(found_at), "eventTime": iso(t + delay)})
        near_first = g % 2 == 0
        place_x = place_a if near_first else rng.choice(PLACES)
        t_x = t_a + days(-3, 3) + hours(-3, 3) if near_first else start + days(0, 29) + hours(0, 9)
        record = {"group": g + 1, "location": loc(place_x), "eventTime": iso(t_x)}
        if g < N_GROUPS // 2:
            lost.append({"id": f"l-n{g + 1:02d}", "description": extra["lost"], "truth": None, **record})
        else:
            found.append({"id": f"f-d{g - N_GROUPS // 2 + 1:02d}", "description": extra["found"], **record})
    rng.shuffle(lost)  # so list order cannot break a score tie in the true item's favour
    rng.shuffle(found)
    return lost, found


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
    old = None
    if os.path.exists(TEXT_OUT):
        with open(TEXT_OUT) as f:
            old = json.load(f)
    if old and "groups" in old:
        print(f"Reusing the descriptions in {TEXT_OUT} (delete it to generate new ones).")
        meta, groups = old["meta"], old["groups"]
    else:
        print(f"Writing descriptions with {CHAT_MODEL} on SoClaaS...")
        meta, groups = generate_groups()
    lost, found = build(groups)
    meta["places_and_times"] = PLACEMENT
    with open(TEXT_OUT, "w") as f:
        json.dump({"meta": meta, "groups": groups, "lost": lost, "found": found}, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {TEXT_OUT}: {len(lost)} lost, {len(found)} found")

    vectors = embed([r["description"] for r in lost + found])
    embedded = {"meta": {**meta, "embed_model": EMBED_MODEL},
                "lost": [{**r, "vecText": vectors[r["description"]]} for r in lost],
                "found": [{**r, "vecText": vectors[r["description"]]} for r in found]}
    with open(EMBED_OUT, "w") as f:
        json.dump(embedded, f)
    print(f"Wrote {EMBED_OUT}")


if __name__ == "__main__":
    main()
