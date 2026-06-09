import hashlib
import json
import re
import unicodedata
import uuid

MAX_STRING_LENGTH = 100_000

UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
HTTP_URL_PATTERN = re.compile(r"^https?://\S+$", re.IGNORECASE)
ISO_DATETIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?(Z|[+-]\d{2}:\d{2})$")

DANGEROUS_KEYS = {"__proto__", "constructor", "prototype"}


def is_dangerous_key(k):
    return k in DANGEROUS_KEYS


def sanitize_string(v):
    return unicodedata.normalize("NFC", v.replace("\x00", ""))


def deep_sanitize(value):
    if isinstance(value, str):
        return sanitize_string(value)
    if isinstance(value, list):
        return [deep_sanitize(v) for v in value]
    if isinstance(value, dict):
        return {k: deep_sanitize(v) for k, v in value.items() if not is_dangerous_key(k)}
    return value


def is_valid_uuid(s):
    return isinstance(s, str) and bool(UUID_PATTERN.match(s))


def normalize_uuid(s):
    return s.lower() if isinstance(s, str) else s


def check_scalar(typ, value):
    if typ == "Integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if typ == "Number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if typ == "Boolean":
        return isinstance(value, bool)
    if typ in ("Date", "DateTime", "Time"):
        return isinstance(value, str) and bool(ISO_DATETIME_PATTERN.match(value))
    if typ == "URL":
        return isinstance(value, str) and bool(HTTP_URL_PATTERN.match(value))
    return isinstance(value, str) and len(value) <= MAX_STRING_LENGTH


def is_embed(v, typ):
    return isinstance(v, dict) and v.get("@type") == typ


def etag_for(item):
    body = json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return '"' + hashlib.sha256(body).hexdigest()[:16] + '"'


def generate_uuid():
    return str(uuid.uuid4())
