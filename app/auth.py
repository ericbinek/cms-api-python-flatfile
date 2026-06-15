import re

from app.models import account as account_model
from app import sessions

# HTTP methods that mutate state. No role grants anonymous writes, so any of these
# without a session is a 401 before routing.
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

ANONYMOUS = {"role": "anonymous", "accountId": None, "username": None}

_BEARER = re.compile(r"^Bearer (.+)$")


class UnauthorizedError(Exception):
    # Thrown when a credential is presented but does not resolve. The server maps
    # it to 401 UNAUTHORIZED. A missing credential is not an error — it is
    # anonymous.
    pass


def _bearer_token(handler):
    header = handler.headers.get("Authorization")
    if not header:
        return None
    match = _BEARER.match(header.strip())
    return match.group(1) if match else ""


def resolve_principal(handler):
    # Resolves the request principal. No Authorization header -> anonymous. A
    # Bearer token that does not resolve to a live session (or a malformed header)
    # raises UnauthorizedError. Fails closed: a presented credential must be valid.
    token = _bearer_token(handler)
    if token is None:
        return ANONYMOUS
    if token == "":
        raise UnauthorizedError()
    session = sessions.resolve_session(token)
    if not session:
        raise UnauthorizedError()
    account = account_model.find_by_id(session["accountId"])
    if not account:
        raise UnauthorizedError()
    return {"role": account["role"], "accountId": account["id"], "username": account["username"]}


def requires_session(method, principal):
    # A write method by an unauthenticated principal needs a session: 401 (Guards
    # for an authenticated-but-unauthorized principal are the router's 403).
    return method in WRITE_METHODS and principal["role"] == "anonymous"
