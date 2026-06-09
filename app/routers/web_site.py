from urllib.parse import parse_qs

from app import http as cms_http
from app import errors as cms_errors
from app.models import web_site as model

BASE = "/web-sites"
MAX_LIMIT = 100
DEFAULT_LIMIT = 20
SYSTEM_FILTER_KEYS = {"limit", "offset", "sort", "order"}


def _parse_list_options(url):
    qs = parse_qs(url.query, keep_blank_values=True)
    errors_list = []

    limit = DEFAULT_LIMIT
    if "limit" in qs:
        try:
            n = int(qs["limit"][0])
        except ValueError:
            n = None
        if n is None or n < 1 or n > MAX_LIMIT:
            errors_list.append(f'Query "limit" must be an integer between 1 and {MAX_LIMIT}.')
        else:
            limit = n

    offset = 0
    if "offset" in qs:
        try:
            n = int(qs["offset"][0])
        except ValueError:
            n = None
        if n is None or n < 0:
            errors_list.append('Query "offset" must be a non-negative integer.')
        else:
            offset = n

    sort = "dateCreated"
    if "sort" in qs:
        v = qs["sort"][0]
        if v not in model.SORTABLE_FIELDS:
            errors_list.append(f'Query "sort" must be one of: {", ".join(sorted(model.SORTABLE_FIELDS))}.')
        else:
            sort = v

    order = "desc"
    if "order" in qs:
        v = qs["order"][0]
        if v not in ("asc", "desc"):
            errors_list.append('Query "order" must be "asc" or "desc".')
        else:
            order = v

    filter_dict = {}
    for key, values in qs.items():
        if key in SYSTEM_FILTER_KEYS:
            continue
        if key not in model.SEARCHABLE_FIELDS:
            errors_list.append(f'Unknown filter field "{key}".')
            continue
        filter_dict[key] = values[0]

    return {"limit": limit, "offset": offset, "sort": sort, "order": order, "filter": filter_dict, "errors": errors_list}


def handle(handler, method, path, url, request_path):
    if path == BASE:
        _handle_collection(handler, method, url, request_path)
        return True
    if path.startswith(BASE + "/"):
        rest = path[len(BASE) + 1:]
        if "/" in rest:
            return False
        _handle_item(handler, method, rest, request_path)
        return True
    return False


def _handle_collection(handler, method, url, request_path):
    if method == "GET":
        opts = _parse_list_options(url)
        if opts["errors"]:
            cms_http.json_error(handler, cms_errors.validation(opts["errors"], request_path))
            return
        opts.pop("errors")
        cms_http.json_response(handler, 200, model.find_all(**opts))
        return
    if method == "POST":
        body = cms_http.parse_body(handler)
        errs = model.validate(body)
        if errs:
            cms_http.json_error(handler, cms_errors.validation(errs, request_path))
            return
        created = model.create(body)
        cms_http.json_response(handler, 201, created, extra_headers={"Location": f"{BASE}/{created['id']}"})
        return
    cms_http.json_error(handler, cms_errors.method_not_allowed(["GET", "POST"], request_path))


def _handle_item(handler, method, item_id, request_path):
    if not cms_http.is_valid_uuid(item_id):
        cms_http.json_error(handler, cms_errors.invalid_id(request_path))
        return

    if method == "GET":
        item = model.find_by_id(item_id)
        if item is None:
            cms_http.json_error(handler, cms_errors.not_found(model.TYPE_NAME, request_path))
            return
        cms_http.json_response(handler, 200, model.embed_refs(item))
        return

    if method == "PUT":
        body = cms_http.parse_body(handler)
        errs = model.validate(body, partial=True)
        if errs:
            cms_http.json_error(handler, cms_errors.validation(errs, request_path))
            return
        current = model.find_by_id(item_id)
        if current is None:
            cms_http.json_error(handler, cms_errors.not_found(model.TYPE_NAME, request_path))
            return
        if_match = handler.headers.get("If-Match")
        if if_match and if_match != "*" and if_match != model.etag_of(current):
            cms_http.json_error(handler, cms_errors.precondition_failed(request_path))
            return
        updated = model.update(item_id, body)
        cms_http.json_response(handler, 200, updated)
        return

    if method == "DELETE":
        current = model.find_by_id(item_id)
        if current is None:
            cms_http.json_error(handler, cms_errors.not_found(model.TYPE_NAME, request_path))
            return
        if_match = handler.headers.get("If-Match")
        if if_match and if_match != "*" and if_match != model.etag_of(current):
            cms_http.json_error(handler, cms_errors.precondition_failed(request_path))
            return
        model.remove(item_id)
        cms_http.json_response(handler, 204, None)
        return

    cms_http.json_error(handler, cms_errors.method_not_allowed(["GET", "PUT", "DELETE"], request_path))
