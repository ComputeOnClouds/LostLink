"""Populate the local stack with sample found items and lost reports (docs/LOCAL.md).

Goes through the real API as the demo users, so the worker categorises, embeds and
matches every item as it would in production. Items that already exist are skipped.

    docker compose exec backend python /app/local/seed.py
"""

import functools
import json
import os
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

API = os.environ.get("SEED_API", "http://localhost:8080")

PLACES = {
    "library": ("NUS Central Library", 1.2966, 103.7723),
    "com1": ("COM1, School of Computing", 1.2950, 103.7737),
    "utown": ("UTown Stephen Riady Centre", 1.3046, 103.7725),
    "deck": ("The Deck, Arts canteen", 1.2944, 103.7725),
    "sports": ("University Sports Centre", 1.2996, 103.7756),
    "e1": ("Engineering Block E1", 1.2988, 103.7711),
    "mrt": ("Kent Ridge MRT", 1.2935, 103.7846),
}

# (account, description, place, hours ago). Staff register found items; individuals report lost ones.
FOUND = [
    ("staff", "Black leather bifold wallet with a red stripe, NUS student card inside", "library", 3),
    ("staff", "Silver MacBook Air 13-inch with a cat sticker on the lid", "com1", 26),
    ("staff", "White AirPods Pro charging case with a small scratch on the front", "utown", 5),
    ("staff", "Set of three keys on a yellow Pikachu keyring", "deck", 30),
    ("staff", "Black Casio digital watch with a rubber strap", "sports", 8),
    ("staff", "Grey North Face backpack with a laptop compartment", "e1", 50),
    ("staff2", "Blue Hydro Flask water bottle covered in travel stickers", "mrt", 6),
    ("staff2", "Navy blue umbrella with a curved wooden handle", "mrt", 5),
    ("staff2", "Red Uniqlo puffer jacket, size M", "mrt", 20),
]
LOST = [
    ("user", "Lost my black leather wallet, it has a red stripe and my student card", "library", 2),
    ("user", "Blue Hydro Flask bottle with lots of stickers on it", "mrt", 7),  # not the umbrella beside it
    ("user", "Lost my AirPods Pro case, white, slightly scratched", "utown", 6),
    ("user", "Black Samsung Galaxy phone with a cracked screen protector", "com1", 10),  # nothing found
    ("user2", "MacBook Air, silver, with a cat sticker", "com1", 28),
    ("user2", "My keys on a Pikachu keychain", "deck", 31),
    ("user2", "Pink Kipling pencil case with pens inside", "library", 1),  # not the wallet found there
]
ACCOUNTS = {
    "user": ("user@lostlink.example", "User!Pass123"),
    "user2": ("user2@lostlink.example", "User2!Pass123"),
    "staff": ("staff@lostlink.example", "Staff!Pass123"),
    "staff2": ("staff2@lostlink.example", "Staff2!Pass123"),
}


def call(method, path, body=None, headers=None):
    request = Request(API + path, method=method, headers={"Content-Type": "application/json", **(headers or {})},
                      data=None if body is None else json.dumps(body).encode())
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        raise SystemExit(f"{method} {path} -> {exc.code} {exc.read().decode()}")


@functools.cache
def login(account):
    email, password = ACCOUNTS[account]
    client_id = call("GET", "/config.json")["userPoolClientId"]
    result = call("POST", "/cognito", {"ClientId": client_id, "AuthFlow": "USER_PASSWORD_AUTH",
                                       "AuthParameters": {"USERNAME": email, "PASSWORD": password}},
                  {"X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth"})
    return {"Authorization": result["AuthenticationResult"]["IdToken"]}


def create(rows, path, list_key):
    for account, description, place, hours in rows:
        auth = login(account)
        if any(i.get("description") == description for i in call("GET", path, headers=auth)[list_key]):
            print(f"  exists   {description}")
            continue
        name, lat, lng = PLACES[place]
        when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours * 3600))
        call("POST", path, {"description": description, "eventTime": when, "location": {
            "name": name, "latitude": lat, "longitude": lng, "provider": "manual", "selectionMethod": "map"}}, auth)
        print(f"  created  {description}  ({account}, {name})")


print("Found items:")
create(FOUND, "/items", "items")
print("Lost reports:")
create(LOST, "/reports", "reports")

print("Waiting for the matching worker (two LLM calls per item, about a minute)...")
users = {account: login(account) for account in ("user", "user2")}
for _ in range(90):
    reports = [r for auth in users.values() for r in call("GET", "/reports", headers=auth)["reports"]]
    if all(r["status"] != "pending_match" for r in reports):
        break
    time.sleep(2)
for r in reports:
    print(f"  {r['status']:<13} {r['description']}")
print("Open http://localhost:5173 and sign in as user@ / user2@ / staff@ / staff2@lostlink.example")
