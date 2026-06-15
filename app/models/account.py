import hashlib
import hmac
import os
import secrets
import uuid

from app.storage import read_collection, write_collection, with_lock

COLLECTION_FILE = "accounts.json"

# PBKDF2-HMAC-SHA256 — a built-in, salted, slow KDF. The stored string is self
# describing (algo, digest, iterations, salt, hash) so a future cost bump can
# verify old hashes and rehash on next login.
_ITERATIONS = 210000
_KEY_LENGTH = 32
_DIGEST = "sha256"


def hash_password(password):
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(_DIGEST, password.encode("utf-8"), salt, _ITERATIONS, _KEY_LENGTH)
    return f"pbkdf2${_DIGEST}${_ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(password, stored):
    if not isinstance(stored, str):
        return False
    parts = stored.split("$")
    if len(parts) != 5 or parts[0] != "pbkdf2":
        return False
    _, digest, iterations_raw, salt_hex, hash_hex = parts
    try:
        iterations = int(iterations_raw)
    except ValueError:
        return False
    if iterations < 1:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac(digest, password.encode("utf-8"), salt, iterations, len(expected))
    return hmac.compare_digest(expected, actual)


def find_by_username(username):
    return next((a for a in read_collection(COLLECTION_FILE) if a.get("username") == username), None)


def find_by_id(account_id):
    return next((a for a in read_collection(COLLECTION_FILE) if a.get("id") == account_id), None)


# A dummy hash kept so an unknown username still runs one PBKDF2 verification: the
# response time does not reveal whether the username existed.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


def authenticate(username, password):
    account = find_by_username(username)
    ok = verify_password(password, account["passwordHash"] if account else _DUMMY_HASH)
    return account if (ok and account) else None


def create_account(username, password, role):
    with with_lock():
        accounts = read_collection(COLLECTION_FILE)
        if any(a.get("username") == username for a in accounts):
            raise ValueError(f"Account already exists: {username}")
        account = {"id": str(uuid.uuid4()), "username": username, "passwordHash": hash_password(password), "role": role}
        accounts.append(account)
        write_collection(COLLECTION_FILE, accounts)
        return account


def seed_admin():
    # Bootstrap: with an empty store and ADMIN_USER/ADMIN_PASSWORD set, the first
    # start creates a single admin. Idempotent — a populated store is a no-op, and
    # missing env vars leave the store empty (every protected write then 401s).
    with with_lock():
        user = os.environ.get("ADMIN_USER")
        password = os.environ.get("ADMIN_PASSWORD")
        if not user or not password:
            return None
        accounts = read_collection(COLLECTION_FILE)
        if accounts:
            return None
        account = {"id": str(uuid.uuid4()), "username": user, "passwordHash": hash_password(password), "role": "admin"}
        write_collection(COLLECTION_FILE, [account])
        return account
