import functools
from datetime import datetime, timezone

from app.storage import read_collection, write_collection, with_lock
from app.validation import (
    check_scalar,
    deep_sanitize,
    etag_for,
    generate_uuid,
    is_dangerous_key,
    is_embed,
    is_valid_uuid,
    normalize_uuid,
    sanitize_string,
)

TYPE_NAME = "CategoryCode"
COLLECTION_FILE = "category-codes.json"

FIELDS = {
        "name": {"kind": "scalar", "type": "Text", "cardinality": "one", "maxLength": 256},
        "description": {"kind": "scalar", "type": "Text", "cardinality": "one", "maxLength": 5000, "multiline": True},
        "codeValue": {"kind": "scalar", "type": "Text", "cardinality": "one", "maxLength": 128},
        "url": {"kind": "scalar", "type": "URL", "cardinality": "one", "maxLength": 2048},
        "inCodeSet": {"kind": "ref", "targets": ["CategoryCodeSet"], "cardinality": "one"},
    }

REQUIRED_FIELDS = {"name", "codeValue", "inCodeSet"}
SEARCHABLE_FIELDS = {"name", "description", "codeValue"}
SORTABLE_FIELDS = {"dateCreated", "dateModified", "name", "description", "codeValue", "url"}

SYSTEM_FIELDS = {"id", "dateCreated", "dateModified", "@context", "@type"}

REF_COLLECTIONS = {"CategoryCodeSet": "category-code-sets.json"}


def _is_empty(value):
    if value is None:
        return True
    if value == "":
        return True
    if isinstance(value, list) and len(value) == 0:
        return True
    return False


def _check_one(spec, value, path):
    kind = spec["kind"]
    if kind == "scalar":
        if not check_scalar(spec["type"], value):
            return [f'Field "{path}" must be a {spec["type"]}.']
        max_length = spec.get("maxLength")
        if max_length is not None and isinstance(value, str) and len(value) > max_length:
            return [f'Field "{path}" must be at most {max_length} characters.']
    elif kind == "enum":
        if value not in spec["values"]:
            return [f'Field "{path}" must be one of: {", ".join(spec["values"])}.']
    elif kind == "ref":
        if not is_valid_uuid(value):
            return [f'Field "{path}" must be a UUID.']
    elif kind == "embed":
        if not is_embed(value, spec["type"]):
            return [f'Field "{path}" must be an inline {spec["type"]} embed with @type set.']
    return []


def _check_field(spec, value, name):
    if spec["cardinality"] == "many":
        if not isinstance(value, list):
            return [f'Field "{name}" must be an array.']
        errors = []
        for i, v in enumerate(value):
            errors.extend(_check_one(spec, v, f"{name}[{i}]"))
        return errors
    return _check_one(spec, value, name)


def validate(data, partial=False):
    if not isinstance(data, dict):
        return ["Request body must be a JSON object."]
    errors = []
    for key in list(data.keys()):
        if not isinstance(key, str) or is_dangerous_key(key):
            errors.append(f'Unknown field "{key}".')
            continue
        if key not in FIELDS and key not in SYSTEM_FIELDS:
            errors.append(f'Unknown field "{key}".')
    if not partial:
        for field in REQUIRED_FIELDS:
            if _is_empty(data.get(field)):
                errors.append(f'Field "{field}" is required.')
    else:
        # A partial update may omit a required field, but must not blank one that
        # is present — that would leave the resource violating its own contract.
        for field in REQUIRED_FIELDS:
            if field in data and _is_empty(data[field]):
                errors.append(f'Field "{field}" must not be empty.')
    for name, spec in FIELDS.items():
        if name not in data:
            continue
        errors.extend(_check_field(spec, data[name], name))
    return errors


def _now():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def sanitize(data):
    """Field-aware input cleaning, run before validation and storage: each known
    scalar string is normalized, stripped of control characters and trimmed, with
    long-form (multiline) fields keeping their internal line breaks. Refs, embeds,
    lists and other values fall back to the conservative property-blind sanitizer.
    The body is cleaned in place: every key is left where it is — dangerous keys
    (__proto__, ...) are deliberately untouched so validate() can reject the body,
    rather than silently dropped here."""
    if not isinstance(data, dict):
        return data
    for key in list(data.keys()):
        if is_dangerous_key(key):
            continue
        value = data[key]
        spec = FIELDS.get(key)
        if spec is not None and spec["kind"] == "scalar" and isinstance(value, str):
            data[key] = sanitize_string(value, spec.get("multiline", False))
        else:
            data[key] = deep_sanitize(value)
    return data


def _normalize_refs(data):
    for name, spec in FIELDS.items():
        if spec["kind"] != "ref" or name not in data:
            continue
        if spec["cardinality"] == "many" and isinstance(data[name], list):
            data[name] = [normalize_uuid(v) for v in data[name]]
        elif isinstance(data[name], str):
            data[name] = normalize_uuid(data[name])
    return data


def _is_number(value):
    # bool is a subclass of int in Python, so exclude it explicitly.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _compare_for_sort(va, vb, direction):
    # Type-aware ordering: numbers numerically, booleans as booleans, everything
    # else lexicographically by string form. Missing values (None) always sort
    # last, regardless of order — never coerced to "".
    a_missing = va is None
    b_missing = vb is None
    if a_missing or b_missing:
        if a_missing and b_missing:
            return 0
        return 1 if a_missing else -1
    if isinstance(va, bool) and isinstance(vb, bool):
        cmp = (va > vb) - (va < vb)
    elif _is_number(va) and _is_number(vb):
        cmp = (va > vb) - (va < vb)
    else:
        sa, sb = str(va), str(vb)
        cmp = (sa > sb) - (sa < sb)
    return cmp * direction


def find_all(filter=None, sort="dateCreated", order="desc", limit=20, offset=0):
    items = read_collection(COLLECTION_FILE)
    if filter:
        for field, value in filter.items():
            if field not in SEARCHABLE_FIELDS:
                continue
            needle = str(value).lower()
            items = [i for i in items if isinstance(i.get(field), str) and needle in i[field].lower()]
    sort_field = sort if sort in SORTABLE_FIELDS else "dateCreated"
    direction = 1 if order == "asc" else -1
    items.sort(key=functools.cmp_to_key(
        lambda a, b: _compare_for_sort(a.get(sort_field), b.get(sort_field), direction)))
    total = len(items)
    return {"items": items[offset:offset + limit], "total": total}


def find_by_id(id):
    if not is_valid_uuid(id):
        return None
    normalized = normalize_uuid(id)
    for item in read_collection(COLLECTION_FILE):
        if item.get("id") == normalized:
            return item
    return None


def embed_refs(item):
    # Embeds referenced entities one level deep for single-resource GET (JSON-LD
    # style): each ref UUID is replaced by the referenced object. List responses
    # stay flat. Embedded objects keep their own refs as UUIDs; a ref that no
    # longer resolves is left as the stored UUID string.
    cache = {}

    def load(file):
        if file not in cache:
            cache[file] = read_collection(file)
        return cache[file]

    def resolve_ref(value, targets):
        if not isinstance(value, str):
            return value
        for target in targets:
            file = REF_COLLECTIONS.get(target)
            if not file:
                continue
            for entry in load(file):
                if entry.get("id") == value:
                    return entry
        return value

    out = dict(item)
    for name, spec in FIELDS.items():
        if spec["kind"] != "ref" or out.get(name) is None:
            continue
        if spec["cardinality"] == "many":
            if not isinstance(out[name], list):
                continue
            out[name] = [resolve_ref(v, spec["targets"]) for v in out[name]]
        else:
            out[name] = resolve_ref(out[name], spec["targets"])
    return out


def create(raw_data):
    with with_lock():
        data = _normalize_refs(raw_data)
        items = read_collection(COLLECTION_FILE)
        now = _now()
        # Client data first, then system-controlled fields override it: a client
        # cannot spoof @context/@type/id/timestamps by sending them in the body.
        item = {**data,
                "@context": "https://schema.org", "@type": TYPE_NAME,
                "id": generate_uuid(), "dateCreated": now, "dateModified": now}
        items.append(item)
        write_collection(COLLECTION_FILE, items)
        return item


def update(id, raw_data):
    with with_lock():
        items = read_collection(COLLECTION_FILE)
        normalized = normalize_uuid(id)
        index = next((i for i, item in enumerate(items) if item.get("id") == normalized), None)
        if index is None:
            return None
        current = items[index]
        data = _normalize_refs(raw_data)
        updated = {**current, **data,
                   "@context": current.get("@context", "https://schema.org"),
                   "@type": current.get("@type", TYPE_NAME),
                   "id": current["id"],
                   "dateCreated": current["dateCreated"],
                   "dateModified": _now()}
        items[index] = updated
        write_collection(COLLECTION_FILE, items)
        return updated


def remove(id):
    with with_lock():
        items = read_collection(COLLECTION_FILE)
        normalized = normalize_uuid(id)
        filtered = [i for i in items if i.get("id") != normalized]
        if len(filtered) == len(items):
            return False
        write_collection(COLLECTION_FILE, filtered)
        return True


def etag_of(item):
    return etag_for(item)
