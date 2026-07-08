from urllib.parse import parse_qs

from app import http as cms_http
from app import errors as cms_errors
from app.models import category_code as model
from app import access

ENTITY = "CategoryCode"
BASE = "/category-codes"
MAX_LIMIT = 100
DEFAULT_LIMIT = 20
SYSTEM_FILTER_KEYS = {"limit", "offset", "sort", "order"}
_ALL = 2 ** 63 - 1  # request the full set from the model before visibility filtering


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


def handle(handler, method, path, url, request_path, principal):
    if path == BASE:
        _handle_collection(handler, method, url, request_path, principal)
        return True
    if path.startswith(BASE + "/"):
        rest = path[len(BASE) + 1:]
        if "/" in rest:
            return False
        _handle_item(handler, method, rest, request_path, principal)
        return True
    return False


def _handle_collection(handler, method, url, request_path, principal):
    role = principal["role"]
    if method == "GET":
        if not access.can(role, ENTITY, "read"):
            cms_http.json_error(handler, cms_errors.forbidden(f'Role "{role}" may not read {ENTITY}.', request_path))
            return
        opts = _parse_list_options(url)
        if opts["errors"]:
            cms_http.json_error(handler, cms_errors.validation(opts["errors"], request_path))
            return
        # Apply read visibility on the full filtered set, then paginate, so total
        # counts only the records this principal may see. Internal fields stripped.
        # The model slices by limit; pass the full set, then visibility-filter here.
        result = model.find_all(filter=opts["filter"], sort=opts["sort"], order=opts["order"], limit=_ALL, offset=0)
        visible = [item for item in result["items"] if access.is_visible(role, ENTITY, item)]
        offset = opts["offset"]
        page = visible[offset:offset + opts["limit"]]
        items = [access.strip_fields(role, item) for item in page]
        cms_http.json_response(handler, 200, {"items": items, "total": len(visible)})
        return
    if method == "POST":
        if not access.can(role, ENTITY, "create"):
            cms_http.json_error(handler, cms_errors.forbidden(f'Role "{role}" may not create {ENTITY}.', request_path))
            return
        body = model.sanitize(cms_http.parse_body(handler))
        readonly = access.readonly_violations(role, body)
        if readonly:
            cms_http.json_error(handler, cms_errors.validation([f'Fields are not writable: {", ".join(readonly)}.'], request_path))
            return
        errs = model.validate(body)
        if errs:
            cms_http.json_error(handler, cms_errors.validation(errs, request_path))
            return
        created = model.create(access.apply_create_defaults(ENTITY, body, principal["accountId"]))
        cms_http.json_response(handler, 201, access.strip_fields(role, created), extra_headers={"Location": f"{BASE}/{created['id']}"}, etag=model.etag_of(created))
        return
    cms_http.json_error(handler, cms_errors.method_not_allowed(["GET", "POST"], request_path))


def _handle_item(handler, method, item_id, request_path, principal):
    role = principal["role"]
    if not cms_http.is_valid_uuid(item_id):
        cms_http.json_error(handler, cms_errors.invalid_id(request_path))
        return

    if method == "GET":
        if not access.can(role, ENTITY, "read"):
            cms_http.json_error(handler, cms_errors.forbidden(f'Role "{role}" may not read {ENTITY}.', request_path))
            return
        item = model.find_by_id(item_id)
        # A record the principal may not see is indistinguishable from a missing
        # one (404, never 403) so its existence is not disclosed.
        if item is None or not access.is_visible(role, ENTITY, item):
            cms_http.json_error(handler, cms_errors.not_found(model.TYPE_NAME, request_path))
            return
        # The ETag names the stored record's version, not the role- and
        # embedding-shaped body -- it must satisfy a later If-Match.
        cms_http.json_response(handler, 200, access.strip_fields(role, model.embed_refs(item)), etag=model.etag_of(item))
        return

    if method == "PUT":
        if not access.can(role, ENTITY, "update"):
            cms_http.json_error(handler, cms_errors.forbidden(f'Role "{role}" may not update {ENTITY}.', request_path))
            return
        body = model.sanitize(cms_http.parse_body(handler))
        readonly = access.readonly_violations(role, body)
        if readonly:
            cms_http.json_error(handler, cms_errors.validation([f'Fields are not writable: {", ".join(readonly)}.'], request_path))
            return
        errs = model.validate(body, partial=True)
        if errs:
            cms_http.json_error(handler, cms_errors.validation(errs, request_path))
            return
        current = model.find_by_id(item_id)
        if current is None:
            cms_http.json_error(handler, cms_errors.not_found(model.TYPE_NAME, request_path))
            return
        owner_field = access.ownership_field(role, "update")
        if owner_field and current.get(owner_field) != principal["accountId"]:
            cms_http.json_error(handler, cms_errors.forbidden("You may only modify your own records.", request_path))
            return
        if_match = handler.headers.get("If-Match")
        if if_match and if_match != "*" and if_match != model.etag_of(current):
            cms_http.json_error(handler, cms_errors.precondition_failed(request_path))
            return
        status = access.status_property(ENTITY)
        if status and status in body and body[status] != current.get(status):
            if not access.transition_allowed(ENTITY, current.get(status), body[status], role):
                cms_http.json_error(handler, cms_errors.forbidden(f'Status transition {current.get(status)} -> {body[status]} is not allowed for role "{role}".', request_path))
                return
        # update() returns None when the record vanished between the lookup
        # above and the write (concurrent delete) -- a 404, same as the lookup.
        updated = model.update(item_id, body)
        if updated is None:
            cms_http.json_error(handler, cms_errors.not_found(model.TYPE_NAME, request_path))
            return
        cms_http.json_response(handler, 200, access.strip_fields(role, updated), etag=model.etag_of(updated))
        return

    if method == "DELETE":
        if not access.can(role, ENTITY, "delete"):
            cms_http.json_error(handler, cms_errors.forbidden(f'Role "{role}" may not delete {ENTITY}.', request_path))
            return
        current = model.find_by_id(item_id)
        if current is None:
            cms_http.json_error(handler, cms_errors.not_found(model.TYPE_NAME, request_path))
            return
        owner_field = access.ownership_field(role, "delete")
        if owner_field and current.get(owner_field) != principal["accountId"]:
            cms_http.json_error(handler, cms_errors.forbidden("You may only delete your own records.", request_path))
            return
        if_match = handler.headers.get("If-Match")
        if if_match and if_match != "*" and if_match != model.etag_of(current):
            cms_http.json_error(handler, cms_errors.precondition_failed(request_path))
            return
        model.remove(item_id)
        cms_http.json_response(handler, 204, None)
        return

    cms_http.json_error(handler, cms_errors.method_not_allowed(["GET", "PUT", "DELETE"], request_path))
