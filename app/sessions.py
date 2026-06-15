import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from app.storage import read_collection, write_collection, with_lock

COLLECTION_FILE = "sessions.json"

_IDLE_TTL = timedelta(minutes=30)          # sliding inactivity window
_ABSOLUTE_TTL = timedelta(hours=8)         # hard cap measured from login
_EXTEND_THRESHOLD = timedelta(seconds=60)  # only persist a slide worth writing


def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _parse(value):
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


def create_session(account_id):
    # Issues a session. The raw token is returned exactly once; the store keeps
    # only its SHA-256 hash, the account, the absolute expiry and the sliding idle
    # expiry.
    with with_lock():
        token = secrets.token_hex(32)
        sessions = read_collection(COLLECTION_FILE)
        now = datetime.now(timezone.utc)
        session = {
            "tokenHash": _hash_token(token),
            "accountId": account_id,
            "createdAt": _iso(now),
            "expiresAt": _iso(now + _ABSOLUTE_TTL),
            "idleExpiresAt": _iso(now + _IDLE_TTL),
        }
        sessions.append(session)
        write_collection(COLLECTION_FILE, sessions)
        return {"token": token, "expiresAt": session["expiresAt"]}


def resolve_session(token):
    # Resolves a raw token to its live session, or None if unknown or expired. An
    # expired session is dropped. On success the idle window slides forward (capped
    # at the absolute expiry) and is persisted only when the move is large enough,
    # so authenticated reads do not write on every request.
    with with_lock():
        token_hash = _hash_token(token)
        sessions = read_collection(COLLECTION_FILE)
        now = datetime.now(timezone.utc)
        index = next((i for i, s in enumerate(sessions) if s.get("tokenHash") == token_hash), None)
        if index is None:
            return None

        session = sessions[index]
        absolute = _parse(session["expiresAt"])
        idle = _parse(session["idleExpiresAt"])
        if now >= absolute or now >= idle:
            sessions.pop(index)
            write_collection(COLLECTION_FILE, sessions)
            return None

        next_idle = min(now + _IDLE_TTL, absolute)
        if next_idle - idle > _EXTEND_THRESHOLD:
            session["idleExpiresAt"] = _iso(next_idle)
            write_collection(COLLECTION_FILE, sessions)
        return {"accountId": session["accountId"], "expiresAt": session["expiresAt"]}


def delete_session(token):
    # Logout / revocation: deletes the session and takes effect immediately.
    with with_lock():
        token_hash = _hash_token(token)
        sessions = read_collection(COLLECTION_FILE)
        remaining = [s for s in sessions if s.get("tokenHash") != token_hash]
        removed = len(remaining) != len(sessions)
        if removed:
            write_collection(COLLECTION_FILE, remaining)
        return removed
