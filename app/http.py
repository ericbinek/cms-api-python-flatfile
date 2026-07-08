import json
import hashlib
import re

MAX_BODY_SIZE = 1024 * 1024
MAX_JSON_DEPTH = 512

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, If-Match, If-None-Match",
    "Access-Control-Expose-Headers": "ETag",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


class BodyTooLargeError(Exception):
    pass


class UnsupportedMediaTypeError(Exception):
    pass


def is_valid_uuid(s):
    return isinstance(s, str) and bool(UUID_PATTERN.match(s))


def _exceeds_max_depth(value, max_depth):
    # Iterative DFS — never recurses, so a deeply nested payload is rejected as
    # invalid JSON (400) instead of risking a RecursionError or unbounded work.
    stack = [(value, 1)]
    while stack:
        v, d = stack.pop()
        if d > max_depth:
            return True
        if isinstance(v, list):
            stack.extend((e, d + 1) for e in v)
        elif isinstance(v, dict):
            stack.extend((x, d + 1) for x in v.values())
    return False


def parse_body(handler):
    length_raw = handler.headers.get("Content-Length", "0")
    try:
        length = int(length_raw or "0")
    except ValueError:
        length = 0
    if length > MAX_BODY_SIZE:
        raise BodyTooLargeError()
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    handler._body_consumed = True
    media_type = handler.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if media_type != "application/json":
        raise UnsupportedMediaTypeError()
    data = json.loads(raw)
    if _exceeds_max_depth(data, MAX_JSON_DEPTH):
        raise json.JSONDecodeError("Maximum nesting depth exceeded", raw.decode("utf-8", "replace"), 0)
    return data if isinstance(data, dict) else {}


def _send_cors_headers(handler):
    for k, v in CORS_HEADERS.items():
        handler.send_header(k, v)


def preflight(handler):
    handler.send_response(204)
    _send_cors_headers(handler)
    handler.end_headers()


def _generate_etag(body_bytes):
    return '"' + hashlib.sha256(body_bytes).hexdigest()[:16] + '"'


# Single-record responses pass the record's canonical ETag (the stored record's
# version, the same value If-Match is checked against). Without one the ETag
# falls back to a hash of the response body; lists and errors have no single
# record version.
def json_response(handler, status, data, extra_headers=None, etag=None):
    if status == 204:
        handler.send_response(204)
        _send_cors_headers(handler)
        handler.end_headers()
        return
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if etag is None:
        etag = _generate_etag(body)
    if_none_match = handler.headers.get("If-None-Match")
    if if_none_match and (if_none_match == etag or if_none_match == "*"):
        handler.send_response(304)
        _send_cors_headers(handler)
        handler.end_headers()
        return
    handler.send_response(status)
    _send_cors_headers(handler)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("ETag", etag)
    if extra_headers:
        for k, v in extra_headers.items():
            handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(body)


def json_error(handler, error, extra_headers=None):
    json_response(handler, error["status"], error, extra_headers)
