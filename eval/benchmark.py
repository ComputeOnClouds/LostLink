"""Hand-authored ~100 lost / ~200 found matching benchmark with hard negatives.

The 4x4 sample (data/sample_dataset.json) only proves the harness runs. This benchmark
is meant to *stress* matching:

- GROUPS: 60 true pairs. Each pair has an owner's lost report (from memory) and a staff
  found report (from the object, different wording), plus a HARD NEGATIVE: another
  found item of the same kind that contradicts at least one detail the owner stated.
- NEAR_MISS_LOST: 20 lost reports with no true match, of a kind that IS among the found
  items (should not alert).
- UNRELATED_LOST: 20 lost reports with no true match and nothing similar found.
- DISTRACTOR_FOUND: 80 assorted found items matching no lost report.

Locations are WGS84 coordinates (the production geographic path), not legacy zones,
and times are spread over a 12-week semester. Pairs are NOT always co-located or
same-day: the band mix below is an explicit assumption that drives how much location
and time can help, so it is recorded in the dataset's ``meta`` and should be reported.
Hard negatives are placed at the same place and week as their pair half of the time.

``build_benchmark(seed)`` is pure and deterministic; vectors are added by generate.py.
Place coordinates are approximate (good to ~100 m), which is enough for scoring.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

# (category, lost report by owner, found report by staff, hard-negative found report)
GROUPS: list[tuple[str, str, str, str]] = [
    ("wallet", "black leather bifold wallet with a faded red stripe, my matric card is inside",
     "dark leather wallet with a worn red stripe, contains an NUS student card",
     "black leather bifold wallet, plain with no markings, contains a bank card"),
    ("bottle", "yellow Hydro Flask with a panda sticker and a dented lid",
     "bright yellow insulated flask, panda decal, lid slightly dented",
     "yellow Hydro Flask with no stickers, lid in good condition"),
    ("umbrella", "navy blue umbrella with a curved wooden handle",
     "dark blue umbrella, wooden crook handle, brass tip",
     "navy blue compact folding umbrella with a black plastic handle"),
    ("laptop", "silver MacBook Air with a cracked NUS sticker on the lid",
     "silver Apple laptop, partly peeled university sticker on the cover",
     "space grey MacBook Pro with no stickers"),
    ("backpack", "red Herschel backpack, the left strap buckle is broken",
     "maroon Herschel rucksack, left shoulder buckle snapped",
     "red Herschel backpack in good condition, both buckles intact, with a keychain"),
    ("headphones", "black Sony wireless headphones in a grey hard case",
     "over-ear Sony headphones stored in a grey zip case",
     "black Bose over-ear headphones, no case"),
    ("glasses", "brown tortoiseshell prescription glasses in a soft pouch",
     "brown-framed spectacles with a tortoise pattern, cloth pouch",
     "black rectangular prescription glasses in a hard blue case"),
    ("jacket", "grey North Face puffer jacket size M with an ink stain on the cuff",
     "grey padded North Face coat, small stain near the wrist",
     "black North Face puffer jacket, size L, clean"),
    ("keys", "three keys on a green carabiner with a bottle opener",
     "three keys clipped to a green carabiner with an opener",
     "two keys on a red carabiner, no opener"),
    ("earbuds", "white AirPods Pro case with a small blue paint mark",
     "white earbud charging case, dab of blue paint on the hinge",
     "white AirPods Pro case in a pink silicone cover, no marks"),
    ("backpack", "teal Fjallraven Kanken with a NASA patch and a broken zip",
     "lime-teal Kanken bag, NASA patch, zip pull missing",
     "teal Fjallraven Kanken, no patches, zips working"),
    ("watch", "black leather-strap analog watch with a scratched face",
     "analog wristwatch, leather band, glass face scuffed",
     "silver metal-strap analog watch, face undamaged"),
    ("lunch bag", "pink insulated lunch bag with a cartoon cat print",
     "pink cooler lunch bag, printed cat cartoon on the side",
     "pink lunch bag with a strawberry print"),
    ("bottle", "clear water bottle covered in stickers of different countries",
     "transparent bottle plastered with assorted country flag decals",
     "clear plastic water bottle, no stickers, black cap"),
    ("vest", "olive green Uniqlo down vest missing the top button",
     "olive Uniqlo puffer gilet, top snap button absent",
     "black Uniqlo down vest, all buttons present"),
    ("phone", "black Samsung Galaxy S23 with a cracked screen protector in a blue case",
     "Samsung phone, black, shattered screen protector, navy rubber case",
     "black Samsung phone in a clear case, screen intact"),
    ("phone", "iPhone 14 in a purple case with a photo of my dog on the back",
     "Apple iPhone in a lilac case with a dog picture insert",
     "iPhone in a plain purple silicone case"),
    ("calculator", "Casio fx-991 calculator with Wei Ling written in marker on the back",
     "Casio scientific calculator, name 'Wei Ling' written on the back cover",
     "Casio fx-991 calculator, no name, missing battery cover"),
    ("power bank", "white Anker power bank with a USB-C cable wrapped around it",
     "white Anker portable charger, USB-C cord wound around it",
     "black Xiaomi power bank, no cable"),
    ("id card", "NUS student card in a clear card holder on a blue lanyard",
     "university matriculation card in a transparent sleeve, blue lanyard attached",
     "NUS staff pass on a red lanyard"),
    ("tablet", "iPad Air in a green folio case with an Apple Pencil attached",
     "Apple tablet in a green flip cover, stylus clipped on",
     "iPad in a black folio case, no pencil"),
    ("pencil case", "pink Kipling pencil case with a monkey keychain, pens inside",
     "pink fabric pencil pouch, small gorilla charm on the zip, contains pens",
     "plain pink pencil case with highlighters inside, no keychain"),
    ("cap", "black New Era baseball cap with a white NY logo",
     "black cap, white NY embroidery, New Era sticker on the brim",
     "black baseball cap with a red Nike swoosh"),
    ("hoodie", "grey NUS Computing hoodie, size L, with a coffee stain on the sleeve",
     "grey School of Computing sweatshirt with hood, stained sleeve",
     "grey NUS Engineering hoodie, size M"),
    ("tote bag", "beige canvas tote bag with a Kinokuniya logo, two textbooks inside",
     "cream canvas tote with a bookstore print, two textbooks inside",
     "beige canvas tote bag printed with a cat, empty"),
    ("sunglasses", "Ray-Ban aviator sunglasses with gold frames in a brown case",
     "gold-rimmed aviator shades in a brown Ray-Ban case",
     "black Ray-Ban Wayfarer sunglasses, no case"),
    ("notebook", "A5 black Moleskine notebook with my handwritten CS2040 lecture notes",
     "black hardcover notebook, handwritten notes on data structures",
     "A5 black Moleskine notebook, blank pages, unused"),
    ("car key", "car key with a Toyota fob and a small Merlion keychain",
     "Toyota remote key with a Merlion charm attached",
     "Honda car key with a leather fob"),
    ("charger", "MacBook USB-C charger with a white braided cable and a label saying JL",
     "white Apple laptop charging brick, braided cable, initials JL on tape",
     "white MacBook charger with a plain rubber cable, no label"),
    ("tumbler", "green Starbucks tumbler with a straw, Singapore edition",
     "green Starbucks cup with lid and straw, Singapore design",
     "black Starbucks tumbler with no straw"),
    ("jacket", "denim jacket with a Totoro pin on the collar",
     "blue jean jacket, Studio Ghibli Totoro badge on the collar",
     "denim jacket with no pins, size S"),
    ("wallet", "small brown card holder with my EZ-Link card and a POSB card",
     "brown leather cardholder containing an EZ-Link card and a bank card",
     "brown leather long wallet with a zip, contains cash"),
    ("bottle", "blue Nalgene bottle with climbing gym stickers",
     "blue Nalgene water bottle with bouldering decals",
     "green Nalgene bottle with no stickers"),
    ("earbuds", "black Samsung Galaxy Buds case with a small dent",
     "black Galaxy Buds charging case, dented corner",
     "white Galaxy Buds case, no damage"),
    ("umbrella", "transparent bubble umbrella with a black handle",
     "clear dome umbrella, black handle",
     "black golf umbrella with a wooden handle"),
    ("shoes", "white Nike Air Force 1 sneakers size 42 in a shoe bag",
     "white Nike trainers, size 42, in a drawstring bag",
     "white Adidas Stan Smith sneakers size 40"),
    ("gym bag", "black Adidas duffel bag with my gym clothes and a towel",
     "black Adidas sports holdall with clothes and a towel inside",
     "black Puma duffel bag, empty"),
    ("raincoat", "yellow raincoat with reflective strips, size S",
     "bright yellow rain jacket, reflective tape, small size",
     "yellow windbreaker with no reflective strips, size XL"),
    ("ring", "silver ring with a small blue stone",
     "silver band set with a little blue gem",
     "gold ring with a small red stone"),
    ("bracelet", "red string bracelet with a jade bead",
     "red cord bracelet, green jade bead",
     "black leather bracelet with a silver clasp"),
    ("textbook", "Introduction to Algorithms (CLRS) with pencil notes, name Arjun inside the cover",
     "CLRS algorithms book, pencil annotations, name Arjun written inside",
     "Introduction to Algorithms textbook, new, no annotations"),
    ("laptop", "black Lenovo ThinkPad with a Linux penguin sticker",
     "black ThinkPad laptop, Tux penguin sticker on the lid",
     "black Lenovo ThinkPad, no stickers, charger attached"),
    ("mouse", "grey Logitech MX Master mouse",
     "grey Logitech wireless mouse, MX model",
     "black Logitech M185 mouse"),
    ("console", "Nintendo Switch in a red carrying case",
     "Nintendo Switch console inside a red zip case",
     "turquoise Nintendo Switch Lite, no case"),
    ("camera", "Fujifilm X100V camera with a brown leather strap",
     "silver Fuji compact camera, brown leather neck strap",
     "black Canon DSLR with a black strap"),
    ("passport", "Indian passport in a black leather cover",
     "passport, Republic of India, black leather sleeve",
     "Indian passport with no cover"),
    ("scarf", "grey wool scarf with tassels",
     "grey woollen scarf, fringed ends",
     "navy wool scarf without tassels"),
    ("e-reader", "Kindle Paperwhite in a cover with a sunflower print",
     "Kindle e-reader, sunflower printed cover",
     "black Kindle, no cover"),
    ("keys", "single key on a Pikachu keyring with a bell",
     "one key on a yellow Pokemon Pikachu keychain with a small bell",
     "single key on a Snorlax keyring"),
    ("bottle", "pink Thermos flask with a name label saying Mei",
     "pink Thermos bottle, name label reading Mei",
     "pink Thermos flask, no label"),
    ("jacket", "black varsity jacket with white sleeves and the letter R on the chest",
     "black-and-white letterman jacket, R patch on the front",
     "black varsity jacket with a letter K patch"),
    ("bag", "small black Longchamp crossbody bag with a lipstick and tissues",
     "black Longchamp sling pouch containing a lipstick and a tissue packet",
     "black Coach crossbody bag with a gold chain"),
    ("glasses", "round gold wire-frame glasses in a black case",
     "gold round metal spectacles, black hard case",
     "round silver wire-frame glasses, no case"),
    ("watch", "Apple Watch with an orange sport loop strap",
     "Apple smartwatch, orange fabric loop band",
     "Apple Watch with a black silicone band"),
    ("hat", "beige bucket hat with a small embroidered strawberry",
     "cream bucket hat, tiny stitched strawberry",
     "beige bucket hat with a sunflower embroidery"),
    ("keyboard", "Keychron mechanical keyboard in a grey sleeve",
     "Keychron keyboard inside a grey fabric pouch",
     "Logitech wireless keyboard, no sleeve"),
    ("racket", "Yonex badminton racket in a blue cover",
     "blue-covered Yonex racquet",
     "Li-Ning badminton racket in a red cover"),
    ("pen case", "black Muji pen case with a set of Copic markers",
     "black Muji pencil pouch full of Copic markers",
     "black Muji pen case with mechanical pencils"),
    ("umbrella", "long red umbrella with a hook handle and a broken spoke",
     "red stick umbrella, J handle, one bent rib",
     "long red umbrella, intact, with a straight handle"),
    ("phone", "Google Pixel 8 in a mint green case with my EZ-Link card in the back slot",
     "Pixel phone in a pale green case, transit card tucked in the back",
     "Google Pixel in a black case, no cards"),
]

# Lost reports with no true match, of a kind that IS among the found items.
NEAR_MISS_LOST: list[tuple[str, str]] = [
    ("wallet", "brown leather bifold wallet with a blue stripe"),
    ("bottle", "yellow Hydro Flask with a koala sticker"),
    ("laptop", "silver MacBook Pro with a SpaceX sticker"),
    ("headphones", "white AirPods Max headphones in a pink smart case"),
    ("jacket", "grey Uniqlo puffer jacket with a hood, size S"),
    ("phone", "black Samsung phone in a red case with a ring holder"),
    ("umbrella", "navy blue umbrella with a white polka-dot pattern"),
    ("backpack", "green Herschel backpack with a laptop sleeve"),
    ("keys", "set of four keys on a blue carabiner"),
    ("calculator", "Casio fx-570 calculator with a blue cover"),
    ("tablet", "iPad mini in a pink case"),
    ("cap", "white Nike baseball cap"),
    ("sunglasses", "black Oakley sunglasses with polarised lenses"),
    ("laptop", "black Lenovo IdeaPad laptop with a Spiderman sticker"),
    ("bracelet", "silver bracelet with heart charms"),
    ("bottle", "blue Thermos flask with dents"),
    ("watch", "Apple Watch with a blue leather strap"),
    ("pencil case", "pink pencil case with a Hello Kitty print"),
    ("racket", "black Yonex racket bag with two rackets inside"),
    ("shoes", "white Nike sneakers size 44 with a green swoosh"),
]

# Lost reports with no true match and nothing similar among found items.
UNRELATED_LOST: list[str] = [
    "antique brass compass engraved with initials",
    "violin in a black hard case",
    "fountain pen with a personalised engraving",
    "box of homemade cookies in a blue tin",
    "architecture model made of white foam board",
    "ukulele in a soft brown gig bag",
    "blue yoga mat with a carrying strap",
    "lab safety goggles with my name on the strap",
    "insulin pen in a small black cooler pouch",
    "matte grey folding bicycle helmet",
    "stack of printed lecture slides in a clear folder",
    "red Samsung T7 external SSD",
    "hearing aid in a small beige case",
    "palm-sized rubber duck figurine",
    "chess set in a wooden folding box",
    "embroidered prayer mat in a green pouch",
    "orange battery-powered camping lantern",
    "skateboard with blue grip tape and stickers",
    "set of acrylic paints in a plastic box",
    "graduation photo in a silver frame",
]

# Found items matching no lost report.
DISTRACTOR_FOUND: list[str] = [
    "single black leather glove, right hand", "coiled white phone charging cable",
    "paperback novel with a cracked spine", "metal reusable straw in a cloth sleeve",
    "folding hand fan with a floral pattern", "blue lanyard with an empty ID holder",
    "small potted succulent in a ceramic pot", "pair of grey running socks with pink heels",
    "stainless steel travel mug, no lid", "green plush dinosaur toy",
    "bundle of black hair ties on a pencil", "reading glasses with a cracked lens, no case",
    "grey hoodie, no logo, size XL", "blue folder of tutorial worksheets",
    "orange umbrella with a broken frame", "HDMI to USB-C adapter",
    "white wired earphones with a 3.5 mm jack", "purple water bottle with a flip lid",
    "black 64 GB USB flash drive", "green supermarket tote bag",
    "single white wireless earbud, left side", "faded red baseball cap",
    "bunch of keys on a metal ring with a supermarket loyalty tag",
    "Tupperware container with a blue lid", "navy cardigan, size M",
    "single silver hoop earring", "set of Muji gel pens held by a rubber band",
    "SUTD student card on a green lanyard", "black 13-inch laptop sleeve, empty",
    "clear plastic file with a bus timetable", "pair of blue flip-flops",
    "white towel with a hotel logo", "pink hair clip", "empty black phone case, cracked",
    "khaki canvas pencil case with erasers", "green Columbia jacket with a hood",
    "stainless steel bento box", "tennis ball", "folded plastic poncho",
    "set of whiteboard markers", "digital thermometer",
    "black Casio digital watch with a rubber strap", "black Dell laptop charger",
    "silver necklace with a cross pendant", "grey Uniqlo compact umbrella",
    "sketchbook with charcoal drawings", "bicycle lock with its key",
    "brown paper bag with a pastry", "pair of blue swimming goggles",
    "lab coat with a name tag reading Tan", "black mini tripod",
    "Texas Instruments graphing calculator", "camouflage cap", "guitar pick in a small tin",
    "purple yoga block", "set of orange highlighters", "white ceramic mug with a chipped rim",
    "grey cardigan with pearl buttons", "blue JBL Bluetooth speaker",
    "children's water bottle with a cartoon print", "black JanSport backpack, no markings",
    "brown leather belt", "grey Sharp scientific calculator",
    "disposable face masks in a ziplock bag", "phone tripod grip",
    "Polaroid photo of a group of friends", "pair of black jeans in a plastic bag",
    "paperback copy of Norwegian Wood", "green umbrella with a duck-head handle",
    "keychain with an Eiffel Tower charm, no keys", "orange tote bag with a library logo",
    "black Muji notebook, partly used", "empty red spectacle case",
    "white 20 W iPhone charging brick", "tube of feather shuttlecocks", "beige trench coat",
    "navy lunch box with chopsticks", "silver key on a plain ring",
    "sports armband phone holder", "gold-coloured hairpin with a pearl",
]

# (name, latitude, longitude, on_campus) — approximate.
PLACES: list[tuple[str, float, float, bool]] = [
    ("NUS Central Library", 1.2966, 103.7723, True),
    ("COM1, School of Computing", 1.2950, 103.7737, True),
    ("UTown Stephen Riady Centre", 1.3046, 103.7725, True),
    ("The Deck, Arts canteen", 1.2944, 103.7725, True),
    ("University Sports Centre", 1.2996, 103.7756, True),
    ("Engineering Block E1", 1.2988, 103.7711, True),
    ("Yusof Ishak House", 1.2985, 103.7748, True),
    ("Frontier canteen, Faculty of Science", 1.2964, 103.7804, True),
    ("TechnoEdge canteen", 1.2978, 103.7716, True),
    ("LT27 lecture theatre", 1.2970, 103.7808, True),
    ("Hon Sui Sen Memorial Library", 1.2929, 103.7742, True),
    ("Prince George's Park Residences", 1.2914, 103.7810, True),
    ("Kent Ridge Bus Terminal", 1.2946, 103.7696, True),
    ("University Hall", 1.2972, 103.7783, True),
    ("NUH Medical Centre", 1.2932, 103.7832, True),
    ("Kent Ridge MRT", 1.2935, 103.7846, False),
    ("one-north MRT", 1.2995, 103.7874, False),
    ("Buona Vista MRT", 1.3072, 103.7903, False),
    ("Dover MRT", 1.3114, 103.7786, False),
    ("Clementi Mall", 1.3150, 103.7643, False),
    ("Holland Village", 1.3112, 103.7959, False),
    ("HarbourFront Centre", 1.2646, 103.8205, False),
    ("Jurong East MRT", 1.3332, 103.7423, False),
]

# Assumed behaviour of true pairs (recorded in meta; change and re-run to test sensitivity).
LOCATION_BANDS = [("same", 0.60), ("nearby", 0.25), ("far", 0.15)]  # same place / <1.5 km / >=1.5 km
NEARBY_MAX_M = 1500.0
DELAY_BANDS = [  # found time minus owner's stated lost time, in hours
    ("hours", 0.65, 0.5, 12.0),
    ("days", 0.20, 12.0, 72.0),
    ("week+", 0.10, 72.0, 336.0),
    ("before", 0.05, -24.0, 0.0),  # owner misremembers: found before the stated time
]
SEMESTER_START = datetime(2026, 8, 10, tzinfo=timezone.utc)
SEMESTER_DAYS = 84
ON_CAMPUS_LOST_SHARE = 0.85
HARD_NEGATIVE_COLOCATED_SHARE = 0.5

# full: 100 lost / 200 found. small: 20 lost / 40 found (a seeded subset of the same items).
SIZES = {
    "full": {"pairs": 60, "near_miss": 20, "unrelated": 20, "distractors": 80},
    "small": {"pairs": 12, "near_miss": 4, "unrelated": 4, "distractors": 16},
}
# realistic: look-alike hard negatives + the band mix above.
# best_case: the 4x4 sample's conditions — no look-alikes (replaced by distractors), every
# true pair found at the stated place within hours. An upper bound, not an estimate.
CONDITIONS = {
    "realistic": {"hard_negatives": True, "location_bands": LOCATION_BANDS,
                  "delay_bands": DELAY_BANDS},
    "best_case": {"hard_negatives": False, "location_bands": [("same", 1.0)],
                  "delay_bands": [("hours", 1.0, 0.5, 12.0)]},
}


def _haversine_m(a: tuple, b: tuple) -> float:
    lat_a, lat_b = math.radians(a[1]), math.radians(b[1])
    dlat, dlon = lat_b - lat_a, math.radians(b[2] - a[2])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(dlon / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(math.sqrt(h))


def _pick(rng: random.Random, bands: list) -> tuple:
    r, acc = rng.random(), 0.0
    for band in bands:
        acc += band[1]
        if r < acc:
            return band
    return bands[-1]


def _location(rng: random.Random, place: tuple, jitter_m: float = 60.0) -> dict:
    """Place + small random offset (people drop pins near, not on, a landmark)."""
    bearing, dist = rng.uniform(0, 2 * math.pi), rng.uniform(0, jitter_m)
    dlat = dist * math.cos(bearing) / 111_320.0
    dlon = dist * math.sin(bearing) / (111_320.0 * math.cos(math.radians(place[1])))
    return {"name": place[0], "latitude": round(place[1] + dlat, 6),
            "longitude": round(place[2] + dlon, 6), "provider": "manual",
            "selectionMethod": "map"}


def _lost_place(rng: random.Random) -> tuple:
    on_campus = rng.random() < ON_CAMPUS_LOST_SHARE
    return rng.choice([p for p in PLACES if p[3] == on_campus])


def _found_place(rng: random.Random, lost_place: tuple, band: str) -> tuple:
    if band == "same":
        return lost_place
    others = [p for p in PLACES if p is not lost_place]
    near = [p for p in others if _haversine_m(lost_place, p) < NEARBY_MAX_M]
    far = [p for p in others if _haversine_m(lost_place, p) >= NEARBY_MAX_M]
    pool = near if band == "nearby" else far
    return rng.choice(pool or others)


def _random_time(rng: random.Random) -> datetime:
    return SEMESTER_START + timedelta(days=rng.uniform(0, SEMESTER_DAYS),
                                      hours=rng.uniform(8, 22))


def _iso(t: datetime) -> str:
    return t.replace(microsecond=0).isoformat()


def _select(sel: random.Random, items: list, n: int, prefer=None) -> list[tuple[int, object]]:
    """Seeded subset of (1-based index, item), keeping list order; all items when n covers
    the list. ``prefer`` items are taken first (e.g. near-misses of selected categories)."""
    indexed = list(enumerate(items, 1))
    if n >= len(indexed):
        return indexed
    first = [x for x in indexed if prefer and prefer(x[1])]
    rest = [x for x in indexed if x not in first]
    chosen = sel.sample(first, min(n, len(first)))
    chosen += sel.sample(rest, n - len(chosen))
    return sorted(chosen, key=lambda x: x[0])


def build_benchmark(seed: int = 5224, size: str = "full", conditions: str = "realistic") -> dict:
    n, cond = SIZES[size], CONDITIONS[conditions]
    rng = random.Random(seed)
    sel = random.Random(f"{seed}-select")  # separate stream: subsetting never shifts `rng`
    lost: list[dict] = []
    found: list[dict] = []

    groups = _select(sel, GROUPS, n["pairs"])
    categories = {g[0] for _, g in groups}
    near_miss = _select(sel, NEAR_MISS_LOST, n["near_miss"], prefer=lambda x: x[0] in categories)
    unrelated = _select(sel, UNRELATED_LOST, n["unrelated"])
    # Without hard negatives, fill their slots with distractors to keep the found count.
    n_distractors = n["distractors"] + (0 if cond["hard_negatives"] else n["pairs"])
    distractors = _select(sel, DISTRACTOR_FOUND, n_distractors)

    for i, (cat, lost_desc, found_desc, neg_desc) in groups:
        lp = _lost_place(rng)
        band = _pick(rng, cond["location_bands"])[0]
        fp = _found_place(rng, lp, band)
        t_lost = _random_time(rng)
        delay_band, _, lo, hi = _pick(rng, cond["delay_bands"])
        t_found = t_lost + timedelta(hours=rng.uniform(lo, hi))

        fid = f"f-p{i:02d}"
        lost.append({"id": f"l-p{i:02d}", "kind": "pair", "category": cat,
                     "description": lost_desc, "location": _location(rng, lp),
                     "eventTime": _iso(t_lost), "truth": fid,
                     "locationBand": band, "delayBand": delay_band})
        found.append({"id": fid, "kind": "pair", "category": cat,
                      "description": found_desc, "location": _location(rng, fp),
                      "eventTime": _iso(t_found)})

        if not cond["hard_negatives"]:
            continue
        if rng.random() < HARD_NEGATIVE_COLOCATED_SHARE:
            np_, t_neg, colocated = lp, t_lost + timedelta(hours=rng.uniform(-72, 72)), True
        else:
            np_, t_neg, colocated = rng.choice(PLACES), _random_time(rng), False
        found.append({"id": f"f-h{i:02d}", "kind": "hard_negative", "category": cat,
                      "description": neg_desc, "location": _location(rng, np_),
                      "eventTime": _iso(t_neg), "colocated": colocated})

    for i, (cat, desc) in near_miss:
        lost.append({"id": f"l-n{i:02d}", "kind": "near_miss", "category": cat,
                     "description": desc, "location": _location(rng, _lost_place(rng)),
                     "eventTime": _iso(_random_time(rng)), "truth": None})

    for i, desc in unrelated:
        lost.append({"id": f"l-u{i:02d}", "kind": "unrelated", "category": None,
                     "description": desc, "location": _location(rng, _lost_place(rng)),
                     "eventTime": _iso(_random_time(rng)), "truth": None})

    for i, desc in distractors:
        found.append({"id": f"f-d{i:02d}", "kind": "distractor", "category": None,
                      "description": desc, "location": _location(rng, rng.choice(PLACES)),
                      "eventTime": _iso(_random_time(rng))})

    # Shuffle so list order cannot break score ties in the true match's favour.
    rng.shuffle(lost)
    rng.shuffle(found)
    return {
        "meta": {
            "source": "benchmark", "seed": seed, "size": size, "conditions": conditions,
            "hard_negatives": cond["hard_negatives"],
            "location_bands": cond["location_bands"], "nearby_max_m": NEARBY_MAX_M,
            "delay_bands": cond["delay_bands"], "semester_days": SEMESTER_DAYS,
            "hard_negative_colocated_share": HARD_NEGATIVE_COLOCATED_SHARE,
        },
        "lost": lost,
        "found": found,
    }
