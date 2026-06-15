import re

from app import http as cms_http
from app import errors as cms_errors
from app import sessions
from app.models import account as account_model

BASE = "/auth"

_BEARER = re.compile(r"^Bearer (.+)$")


def _bearer_token(handler):
    header = handler.headers.get("Authorization")
    if not header:
        return None
    match = _BEARER.match(header.strip())
    return match.group(1) if match else None


def handle(handler, method, path, url, request_path, principal):
    # The principal is attached by the server middleware before routing. login is
    # reachable anonymously; logout and me require a live session.
    if path == BASE + "/login":
        if method != "POST":
            cms_http.json_error(handler, cms_errors.method_not_allowed(["POST"], request_path))
            return True
        body = cms_http.parse_body(handler)
        if not isinstance(body.get("username"), str) or not isinstance(body.get("password"), str):
            cms_http.json_error(handler, cms_errors.validation(['Fields "username" and "password" are required.'], request_path))
            return True
        # Same 401 for unknown user and wrong password — no user enumeration.
        account = account_model.authenticate(body["username"], body["password"])
        if not account:
            cms_http.json_error(handler, cms_errors.unauthorized(request_path))
            return True
        issued = sessions.create_session(account["id"])
        cms_http.json_response(handler, 200, {
            "token": issued["token"],
            "account": {"id": account["id"], "username": account["username"], "role": account["role"]},
            "expiresAt": issued["expiresAt"],
        })
        return True

    if path == BASE + "/logout":
        if method != "POST":
            cms_http.json_error(handler, cms_errors.method_not_allowed(["POST"], request_path))
            return True
        # Idempotent by token: a missing or already-deleted token is 401.
        token = _bearer_token(handler)
        removed = sessions.delete_session(token) if token else False
        if not removed:
            cms_http.json_error(handler, cms_errors.unauthorized(request_path))
            return True
        cms_http.json_response(handler, 204, None)
        return True

    if path == BASE + "/me":
        if method != "GET":
            cms_http.json_error(handler, cms_errors.method_not_allowed(["GET"], request_path))
            return True
        if principal["role"] == "anonymous":
            cms_http.json_error(handler, cms_errors.unauthorized(request_path))
            return True
        cms_http.json_response(handler, 200, {
            "account": {"id": principal["accountId"], "username": principal["username"], "role": principal["role"]},
        })
        return True

    return False
