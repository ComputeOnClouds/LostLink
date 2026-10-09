# Location search, map selection and geographic matching

Lost and found forms share `frontend/src/LocationPicker.tsx`, embedded in
`ItemEditor.tsx`. A selected OneMap result fills a name, address and WGS84 point.
Leaflet loads lazily with OneMap raster tiles; clicking the map or dragging the pin
sets the actual loss/find location. Coordinate entry provides a keyboard alternative.
An optional note records floors or landmarks. Search failures do not prevent manual
selection. Found location means where the item was discovered, not its collection office.

## Account setup

1. Register an account at https://www.onemap.gov.sg/apidocs/register.
2. In AWS Secrets Manager, create a **String** secret containing JSON with `email` and
   `password` keys for that account. Enter values in the AWS console; do not commit them,
   paste them into a shell command, or put them in frontend configuration.
3. Set `ONEMAP_SECRET_ARN` to the secret's complete ARN when synthesizing/deploying
   `LostLink-Api`. The CDK grants read permission only to `LocationsFn`.
   Use a secret in the API stack's region. A customer-managed KMS key also needs an
   explicit decrypt grant to the function; the default Secrets Manager key needs no
   extra key configuration.
4. Deploy the API and matching backend before deploying the frontend. No new DynamoDB
   table or index is required. Set `LOCATION_HALF_DISTANCE_METRES` at matching-stack
   deploy time to override the initial 500 m distance half-life.

Without the secret ARN, the route returns a recoverable 503 and manual selection works.
The ARN is configuration, not the secret value. Tokens are generated server-side through
`/api/auth/post/getToken`, cached per warm Lambda, renewed ahead of expiry and refreshed
once for authentication errors. JSON `error` responses with HTTP 200 are handled too.
Do not log credentials, tokens, upstream bodies or user search queries.

## API and storage

`GET /locations/search?q=...` requires an Individual or Staff Cognito account. Queries
are normalized and limited to 2–120 characters. OneMap search uses `returnGeom=Y`,
`getAddrDetails=Y`, `pageNum=1`; the proxy returns up to five distinct usable results.
Responses expose only normalized suggestion fields. The browser debounces by 300 ms,
aborts obsolete searches and ignores stale results. API Gateway applies a best-effort
route throttle of 3 requests/second with a burst of 5. This is not a guaranteed provider
quota: other deployments, cold-start authentication and retries also consume calls.
The proxy has a bounded 128-entry,
five-minute cache per warm instance, not a distributed cache or global rate limiter.
Each upstream request times out after five seconds; authentication gets at most one retry.
429 is returned with `Retry-After: 10`; other upstream/configuration failures return 503.

An item stores a nested `location` map:

```json
{
  "name": "User-confirmed place name",
  "address": "Optional selected address",
  "latitude": 1.2966,
  "longitude": 103.7736,
  "provider": "onemap",
  "selectionMethod": "search",
  "providerPlaceId": null,
  "note": "Optional floor or landmark"
}
```

Coordinates above are illustrative. DynamoDB stores them as Numbers (`Decimal` in
Python), not strings; API JSON returns numeric values. Names, addresses and provenance
are labels, not primary keys or proof of accuracy. Both create/edit handlers share
validation. The Singapore service envelope is latitude 1.13–1.57, longitude
103.50–104.12, including offshore islands; it is a bounding rectangle, not a national
boundary polygon. Swapped/out-of-area coordinates, non-finite values, booleans and
incomplete points are rejected. Name is required (max 200), address/note max 500.

OneMap's documented search response has no stable provider place ID. The optional
field is reserved for future providers. A moved pin sets `selectionMethod=map` and
clears that ID and the original address, retaining OneMap provenance for the selected label.
Changing search text clears the old point until a suggestion or manual point is chosen.

Lost reports may also store `searchRadiusMetres`: `null` (any distance), 500, 1000,
2000 or 5000. A finite radius requires a confirmed point; staff cannot set this field
on found items. Legacy clients may continue sending a non-empty `locationZone`, and
old rows deserialize with no coordinates. Existing forms show the legacy zone until
the user selects a replacement. No ambiguous names are automatically geocoded.

## Matching and privacy

The pure Haversine function in `backend/pipeline/location.py` computes great-circle
distance in metres using an Earth radius of 6,371,008.8 m. It is straight-line surface
distance, not travel distance. No OneMap call is made during matching.

`BlendedScorer` uses `0.5 ** (distance / half_distance_metres)` when both sides have
coordinates. At the default 500 m half-distance, scores are 1 at the same point,
0.5 at 500 m and 0.25 at 1 km. Existing blend weights/threshold remain unchanged.
Otherwise the scorer uses legacy zones when both are present, or omits the location
component when it cannot compare either representation.

An explicit radius filters candidates before scoring, **always using the lost report's
radius**, including jobs triggered by registering/editing a found item. The boundary
is inclusive. Candidates without coordinates are excluded from strict-radius searches.
Without a radius, distance is a ranking signal and distant items remain eligible.
The worker invalidates prior matches before rebuilding the result set as before.

Coordinate/radius edits enqueue rematching, preserve text embeddings and use the
existing conditional revision writes. Label/note-only edits save without rematching.
Owners see their own points; staff see their own organisation's inventory. Found-item
points remain hidden from claimants until the existing claim approval gate permits
item details. Match suggestion responses do not expose coordinates or distances.

The prototype queries existing opposing-item GSIs then computes distance in Python.
At scale, use geohash/grid candidate retrieval across **all intersecting cells**, followed
by exact distance filtering, or a dedicated spatial index. A DynamoDB FilterExpression
alone does not avoid the underlying reads.

The evaluation harness accepts the same `location` and `searchRadiusMetres` fields.
`LOCATION_HALF_DISTANCE_METRES` also configures its scorer. Old sample datasets still
exercise zone matching; do not interpret passing those as coordinate-quality evidence.

## Verification before merge — Harsh

**DO NOT MERGE until Harsh Reviews and tests it.**

Offline checks:

```bash
cd backend
AWS_DEFAULT_REGION=ap-southeast-2 AWS_EC2_METADATA_DISABLED=true .venv/bin/python -m pytest -q
cd ../frontend
npm ci
npx playwright install chromium
npm run test:e2e
npm run build
cd ../infra
npx tsc --noEmit
CDK_DEFAULT_ACCOUNT=123456789012 CDK_DEFAULT_REGION=ap-southeast-2 npm run synth -- --quiet
```

The browser tests run a local fixture using the real editor and mocked search/save
responses; tile requests are aborted deliberately to verify fallback behavior. They
do not test live OneMap coverage or AWS authorization.

After configuring credentials in a test deployment:

- Search partial/full names for Central Library, VivoCity, an MRT station, a park,
  a street address and a six-digit postal code. Verify relevance, latency and pin position.
- Confirm the account's actual rate limit; published OneMap workshop materials differ
  (250 vs 300 calls/min). Test 429 handling without repeatedly hammering the provider.
- Save/reopen both roles' items; adjust the point and confirm rematching. Rename/add a
  note and confirm no unnecessary rematch. Edit a legacy item without losing its zone.
- Exercise search outages, manual map clicking/dragging, keyboard coordinate entry,
  mobile layout and changing text after selection. Confirm browser requests contain
  no OneMap credentials/token.
- Test a matching pair inside/outside the chosen radius in both job orientations;
  verify matching notification dedup and that unapproved claims reveal no found location.
- Sweep coordinate-labelled evaluation data before changing weights, threshold or
  half-distance. The initial 500 m value is a proposal, not a validated optimum.

The picker displays OneMap/SLA attribution and links the Singapore Open Data Licence.
Sources: [search](https://www.onemap.gov.sg/apidocs/search),
[authentication](https://www.onemap.gov.sg/apidocs/authentication),
[tile example](https://www.onemap.gov.sg/docs/maps/index.html),
[API terms](https://www.onemap.gov.sg/legal/apitermsofservice.html),
[data licence](https://www.onemap.gov.sg/legal/opendatalicence.html).
