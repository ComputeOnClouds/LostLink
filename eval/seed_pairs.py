"""Hand-authored lost/found description pairs + distractors.

A Claude-free source of ground-truth descriptions so a real (Titan-embedded) evaluation
dataset can be produced even when Anthropic model access requires the use-case form.
generate.py uses these when GENERATE_SOURCE=seed (or Claude is unavailable). Each pair's
lost_desc (owner-from-memory) and found_desc (staff-from-item) describe the same object
in different words.
"""

PAIRS = [
    {"lost_desc": "black leather bifold wallet with a faded red stripe",
     "found_desc": "dark leather wallet, worn red stripe across the front"},
    {"lost_desc": "yellow Hydro Flask bottle with a panda sticker and a dented lid",
     "found_desc": "bright yellow flask, panda decal, lid slightly dented"},
    {"lost_desc": "navy blue umbrella with a curved wooden handle",
     "found_desc": "dark blue umbrella, wooden crook handle, brass tip"},
    {"lost_desc": "silver MacBook Air with a cracked NUS sticker on the lid",
     "found_desc": "silver Apple laptop, partly-peeled university sticker on cover"},
    {"lost_desc": "red Herschel backpack with a broken left strap buckle",
     "found_desc": "maroon Herschel rucksack, left shoulder buckle snapped"},
    {"lost_desc": "black Sony wireless headphones in a hard grey case",
     "found_desc": "over-ear Sony headphones stored in a grey zip case"},
    {"lost_desc": "brown tortoiseshell prescription glasses in a soft pouch",
     "found_desc": "brown-framed spectacles, tortoise pattern, cloth pouch"},
    {"lost_desc": "grey North Face puffer jacket, size M, ink stain on cuff",
     "found_desc": "grey padded North Face coat, small stain near the wrist"},
    {"lost_desc": "set of three keys on a green carabiner with a bottle opener",
     "found_desc": "three keys clipped to a green carabiner with an opener"},
    {"lost_desc": "white AirPods Pro case with a small blue paint mark",
     "found_desc": "white earbud charging case, dab of blue paint on the hinge"},
    {"lost_desc": "teal Kanken backpack with a NASA patch and broken zip",
     "found_desc": "lime-teal Fjallraven bag, NASA patch, zip pull missing"},
    {"lost_desc": "black leather-strap analog watch with a scratched face",
     "found_desc": "analog wristwatch, leather band, glass face scuffed"},
    {"lost_desc": "pink insulated lunch bag with a cartoon cat print",
     "found_desc": "pink cooler lunch bag, printed cat cartoon on the side"},
    {"lost_desc": "clear water bottle covered in travel country stickers",
     "found_desc": "transparent bottle plastered with assorted country decals"},
    {"lost_desc": "green Uniqlo down vest with a missing top button",
     "found_desc": "olive Uniqlo puffer gilet, top snap button absent"},
]

DISTRACTOR_FOUND = [
    "a single black leather glove, right hand",
    "a coiled white phone charging cable",
    "a paperback novel with a cracked spine",
    "a metal reusable straw in a cloth sleeve",
    "a folding hand fan with a floral pattern",
    "a blue lanyard with an empty ID holder",
    "a small potted succulent in a ceramic pot",
    "a pair of running socks, grey with pink heels",
    "a stainless steel travel mug, no lid",
    "a child's plush dinosaur toy, green",
]

DISTRACTOR_LOST = [
    "an antique brass compass engraved with initials",
    "a hand-knitted scarf in maroon and gold stripes",
    "a vintage film camera in a tan case",
    "a fountain pen with a personalised engraving",
    "a beaded bracelet with a small silver charm",
]
