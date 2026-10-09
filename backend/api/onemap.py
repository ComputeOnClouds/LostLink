"""OneMap proxy client. Credentials and tokens stay inside the request Lambda."""

from collections import OrderedDict
import json
import math
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pipeline.location import in_service_area

BASE_URL = "https://www.onemap.gov.sg"


class OneMapError(Exception):
    def __init__(self, status=503):
        super().__init__("Place search is temporarily unavailable. Choose on the map or try again.")
        self.status = status


def _request(path, token=None, data=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = token
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(BASE_URL + path, headers=headers,
                      data=json.dumps(data).encode() if data is not None else None)
    try:
        with urlopen(request, timeout=5) as response:
            result = json.load(response)
        if not isinstance(result, dict):
            raise OneMapError()
        return result
    except HTTPError as exc:
        # Never forward provider bodies, URLs or credential-bearing request objects.
        raise OneMapError(429 if exc.code == 429 else exc.code if exc.code in (401, 403) else 503) from None
    except (URLError, TimeoutError, ValueError, OSError):
        raise OneMapError() from None


class OneMapClient:
    def __init__(self, credentials=None, request=_request, clock=time.time):
        self._credentials = credentials
        self._request = request
        self._clock = clock
        self._token = None
        self._expires = 0
        self._cache = OrderedDict()

    def _load_credentials(self):
        if self._credentials is not None:
            return self._credentials
        secret_arn = os.environ.get("ONEMAP_SECRET_ARN")
        if not secret_arn:
            raise OneMapError()
        import boto3
        try:
            response = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)
            credentials = json.loads(response["SecretString"])
            if not isinstance(credentials, dict):
                raise ValueError()
            return credentials
        except Exception:
            raise OneMapError() from None

    def _get_token(self, force=False):
        if not force and self._token and self._clock() < self._expires - 60:
            return self._token
        credentials = self._load_credentials()
        if not credentials.get("email") or not credentials.get("password"):
            raise OneMapError()
        response = self._request("/api/auth/post/getToken", data={
            "email": credentials["email"], "password": credentials["password"],
        })
        try:
            token = response["access_token"]
            expires = float(response["expiry_timestamp"])
            if not isinstance(token, str) or not token or not math.isfinite(expires) or expires <= self._clock():
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise OneMapError() from None
        self._token, self._expires = token, expires
        return token

    def search(self, query):
        key = query.casefold()
        cached = self._cache.get(key)
        if cached and self._clock() < cached[0]:
            self._cache.move_to_end(key)
            return cached[1]
        path = "/api/common/elastic/search?" + urlencode({
            "searchVal": query, "returnGeom": "Y", "getAddrDetails": "Y", "pageNum": 1,
        })
        # Refresh once for either HTTP authentication errors or OneMap's HTTP-200 errors.
        for attempt in range(2):
            try:
                response = self._request(path, token=self._get_token(force=attempt == 1))
            except OneMapError as exc:
                if exc.status in (401, 403) and attempt == 0:
                    continue
                raise OneMapError(429 if exc.status == 429 else 503) from None
            if response.get("error"):
                message = str(response["error"]).lower()
                if "token" in message and attempt == 0:
                    continue
                raise OneMapError(429 if "limit" in message else 503)
            break
        rows = response.get("results")
        if not isinstance(rows, list):
            raise OneMapError()
        suggestions, seen = [], set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                latitude = float(row["LATITUDE"])
                longitude = float(row.get("LONGITUDE", row.get("LONGTITUDE")))
            except (KeyError, ValueError, TypeError):
                continue
            if not in_service_area(latitude, longitude):
                continue
            building = str(row.get("BUILDING") or "").strip()
            name = building if building.upper() not in ("", "NIL", "NA") else str(row.get("SEARCHVAL") or row.get("ADDRESS") or "").strip()
            if not name:
                continue
            identity = (name.casefold(), round(latitude, 6), round(longitude, 6))
            if identity in seen:
                continue
            seen.add(identity)
            suggestions.append({
                "name": name[:200], "address": str(row.get("ADDRESS") or "")[:500],
                "latitude": latitude, "longitude": longitude,
                "provider": "onemap", "selectionMethod": "search",
            })
            if len(suggestions) == 5:
                break
        self._cache[key] = (self._clock() + 300, suggestions)
        self._cache.move_to_end(key)
        while len(self._cache) > 128:
            self._cache.popitem(last=False)
        return suggestions
