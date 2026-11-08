"""Local stand-in for LostLink's AWS compute, running the real handlers (docs/LOCAL.md).

  * HTTP API: routes as in infra/lib/api-stack.ts; the Cognito JWT is checked like the
    API Gateway authorizer and its claims passed to the handler in the event.
  * A thread polls the match queue and invokes pipeline.lambda_worker (cf. the SQS
    trigger in matching-stack.ts).
  * POST /cognito proxies the browser's Cognito calls to moto and runs the
    post-confirmation trigger after ConfirmSignUp, which moto doesn't.
  * GET /config.json serves the SPA's runtime config.
"""

import importlib
import json
import os
import re
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import Request, urlopen

import boto3
import jwt

import bootstrap

REGION = os.environ["AWS_REGION"]
MOTO = os.environ["AWS_ENDPOINT_URL"]  # http://moto:5000 inside Docker
MOTO_PUBLIC = "http://localhost:5050"  # the same emulator, as the browser sees it
API_PUBLIC = "http://localhost:8080"

ROUTES = {  # handler module -> "METHOD /path"; keep in sync with api-stack.ts
    "locations": ["GET /locations/search"],
    "reports": ["POST /uploads", "POST /reports", "GET /reports", "GET /reports/{itemId}",
                "PATCH /reports/{itemId}", "DELETE /reports/{itemId}"],
    "staff": ["POST /items/uploads", "POST /items", "GET /items", "GET /items/{itemId}",
              "PATCH /items/{itemId}", "DELETE /items/{itemId}"],
    "descriptions": ["POST /descriptions/generate"],
    "claims": ["GET /matches", "POST /claims/uploads", "POST /claims", "GET /claims", "GET /claims/{claimId}",
               "POST /claims/{claimId}/respond", "POST /claims/{claimId}/cancel", "GET /org/claims",
               "GET /org/claims/{claimId}", "POST /org/claims/{claimId}/request-info",
               "POST /org/claims/{claimId}/approve", "POST /org/claims/{claimId}/reject",
               "POST /org/claims/{claimId}/reserve", "POST /org/claims/{claimId}/handover"],
}
_ROUTES = sorted(  # literal paths before templated ones, as in API Gateway
    ((route, re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", route.split(" ")[1]) + "$"), f"api.{name}_handler")
     for name, routes in ROUTES.items() for route in routes),
    key=lambda r: "{" in r[0],
)

POOL_ID = CLIENT_ID = None  # set by bootstrap in main()
_jwks = None
_lock = threading.Lock()  # one invocation at a time, so handlers needn't be thread-safe


def invoke(module, event):
    with _lock:
        return importlib.import_module(module).handler(event, None)


def verify(header):
    """Validate the Cognito ID token as the API Gateway JWT authorizer does."""
    global _jwks
    _jwks = _jwks or jwt.PyJWKClient(f"{MOTO}/{POOL_ID}/.well-known/jwks.json")
    token = (header or "").removeprefix("Bearer ")
    return jwt.decode(token, _jwks.get_signing_key_from_jwt(token).key, algorithms=["RS256"],
                      audience=CLIENT_ID, issuer=f"https://cognito-idp.{REGION}.amazonaws.com/{POOL_ID}")


def post_confirmation(username):
    user = boto3.client("cognito-idp").admin_get_user(UserPoolId=POOL_ID, Username=username)
    invoke("api.post_confirmation", {
        "triggerSource": "PostConfirmation_ConfirmSignUp",
        "userPoolId": POOL_ID,
        "userName": user["Username"],
        "request": {"userAttributes": {a["Name"]: a["Value"] for a in user["UserAttributes"]}},
    })


class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):  # CORS preflight
        self._send(204, {"Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE",
                         "Access-Control-Allow-Headers": self.headers.get("Access-Control-Request-Headers", "*")}, b"")

    def do_GET(self):
        url = urlsplit(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if url.path == "/config.json":
            return self._json(200, {"apiUrl": API_PUBLIC, "region": REGION,
                                    "userPoolId": POOL_ID, "userPoolClientId": CLIENT_ID})
        if url.path == "/cognito":
            return self._cognito(body)
        match = next(((route, m, module) for route, rx, module in _ROUTES
                      if route.startswith(self.command + " ") and (m := rx.match(url.path))), None)
        if not match:
            return self._json(404, {"message": "Not Found"})
        route, m, module = match
        try:
            claims = verify(self.headers.get("Authorization"))
        except jwt.PyJWTError:
            return self._json(401, {"message": "Unauthorized"})
        event = {
            "routeKey": route,
            "pathParameters": m.groupdict() or None,
            "queryStringParameters": dict(parse_qsl(url.query)) or None,
            "body": body.decode() or None,
            "requestContext": {"authorizer": {"jwt": {"claims": claims}}},
        }
        try:
            result = invoke(module, event)
        except Exception:
            traceback.print_exc()
            return self._json(500, {"message": "Internal Server Error"})
        # Presigned S3 URLs name the emulator's in-Docker address; give the browser's.
        data = (result.get("body") or "").replace(MOTO, MOTO_PUBLIC).encode()
        self._send(result["statusCode"], result.get("headers") or {}, data)

    do_POST = do_PATCH = do_DELETE = do_GET

    def _cognito(self, body):
        target = self.headers["X-Amz-Target"]
        request = Request(MOTO + "/", data=body, headers={
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": target,
            "Host": f"cognito-idp.{REGION}.amazonaws.com",  # tells moto the region
        })
        try:
            with urlopen(request) as response:
                status, data = response.status, response.read()
        except HTTPError as exc:
            status, data = exc.code, exc.read()
        if status == 200 and target.endswith(".ConfirmSignUp"):
            post_confirmation(json.loads(body)["Username"])
        self._send(status, {"Content-Type": "application/x-amz-json-1.1"}, data)

    def _json(self, status, payload):
        self._send(status, {"Content-Type": "application/json"}, json.dumps(payload).encode())

    def _send(self, status, headers, data):
        self.send_response(status)
        for name, value in {"Access-Control-Allow-Origin": "*", **headers, "Content-Length": str(len(data))}.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)


def poll_match_queue():
    sqs, url = boto3.client("sqs"), os.environ["MATCH_QUEUE_URL"]
    while True:
        try:
            messages = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=5, WaitTimeSeconds=10).get("Messages", [])
            if not messages:
                continue
            records = [{"messageId": m["MessageId"], "body": m["Body"]} for m in messages]
            failed = {f["itemIdentifier"] for f in invoke("pipeline.lambda_worker", {"Records": records})["batchItemFailures"]}
            for m in messages:  # failed ones stay queued: retried, then DLQ after 3 tries
                if m["MessageId"] not in failed:
                    sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])
        except Exception:
            traceback.print_exc()
            time.sleep(3)


def main():
    global POOL_ID, CLIENT_ID
    POOL_ID, CLIENT_ID = bootstrap.run()
    threading.Thread(target=poll_match_queue, daemon=True).start()
    print(f"LostLink local API on {API_PUBLIC}", flush=True)
    try:
        ThreadingHTTPServer(("", 8080), Handler).serve_forever()
    except KeyboardInterrupt:  # watchfiles restarts us on code changes
        pass


if __name__ == "__main__":
    main()
