import atexit
import json
import os
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from app.models import blog_posting as _blog_posting_mod
from app.models import person as _person_mod
from app.models import organization as _organization_mod
from app.models import web_page as _web_page_mod
from app.models import image_object as _image_object_mod
from app.models import video_object as _video_object_mod
from app.models import audio_object as _audio_object_mod
from app.models import category_code as _category_code_mod
from app.models import category_code_set as _category_code_set_mod
from app.models import defined_term as _defined_term_mod
from app.models import defined_term_set as _defined_term_set_mod
from app.models import comment as _comment_mod
from app.models import web_site as _web_site_mod
from app.models import site_navigation_element as _site_navigation_element_mod
from app.models.account import hash_password
from app.access import READONLY_FIELDS

MODELS = {
    "BlogPosting": _blog_posting_mod,
    "Person": _person_mod,
    "Organization": _organization_mod,
    "WebPage": _web_page_mod,
    "ImageObject": _image_object_mod,
    "VideoObject": _video_object_mod,
    "AudioObject": _audio_object_mod,
    "CategoryCode": _category_code_mod,
    "CategoryCodeSet": _category_code_set_mod,
    "DefinedTerm": _defined_term_mod,
    "DefinedTermSet": _defined_term_set_mod,
    "Comment": _comment_mod,
    "WebSite": _web_site_mod,
    "SiteNavigationElement": _site_navigation_element_mod,
}

REPO_ROOT = Path(__file__).resolve().parents[1]

_server = None

# Auth is mandatory on writes. The entity suite drives the API as an admin (who
# sees and may do everything), so the CRUD contract is exercised unchanged. The
# active bearer token is module scoped so the request helpers attach it without
# threading it through every call.
DEFAULT_ADMIN = {"username": "admin", "password": "bootstrap-admin-secret", "role": "admin"}
_auth_token = None


def set_auth_token(token):
    global _auth_token
    _auth_token = token


def _account_record(spec):
    return {"id": str(uuid.uuid4()), "username": spec["username"], "passwordHash": hash_password(spec["password"]), "role": spec["role"]}


def _free_port():
    while True:
        port = random.randint(14000, 14999)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue


class _Server:
    # Starts a fresh server against a temp data dir. By default the account store
    # is seeded with one admin and the server carries that admin's token. Pass
    # accounts=[...] to seed a specific set, or env={"ADMIN_USER": ...} to exercise
    # the env bootstrap (no store written).
    def __init__(self, accounts=None, env=None):
        self.port = _free_port()
        self.data_dir = tempfile.mkdtemp(prefix="cms-test-py-")

        seed = accounts
        if seed is None and env is None:
            seed = [DEFAULT_ADMIN]
        if seed is not None:
            with open(os.path.join(self.data_dir, "accounts.json"), "w", encoding="utf-8") as f:
                json.dump([_account_record(a) for a in seed], f, indent=2, ensure_ascii=False)

        # Default the rate limits high so the conformance suite never trips them
        # — all requests share one process and one loopback IP. The rate-limit
        # suite sets small values through env to exercise the limiter on purpose.
        proc_env = {**os.environ, "PORT": str(self.port), "DATA_DIR": self.data_dir, "PYTHONPATH": str(REPO_ROOT),
                    "RATE_LIMIT_READ_PER_MINUTE": "1000000", "RATE_LIMIT_WRITE_PER_MINUTE": "1000000"}
        proc_env.update(env or {})
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "app"],
            cwd=str(REPO_ROOT),
            env=proc_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._wait_for_health()

        admin = next((a for a in (seed or []) if a["role"] == "admin"), None)
        self.token = login(self, admin["username"], admin["password"]) if admin else None

    def _wait_for_health(self):
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(self.base_url + "/health", timeout=1) as r:
                    if r.status == 200:
                        return
            except (urllib.error.URLError, ConnectionResetError):
                pass
            time.sleep(0.05)
        self.stop()
        raise RuntimeError("Server did not become healthy within 10s")

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        shutil.rmtree(self.data_dir, ignore_errors=True)


def start_server(accounts=None, env=None):
    return _Server(accounts=accounts, env=env)


def login(server, username, password):
    r = request_json(server, "POST", "/auth/login", {"username": username, "password": password}, no_auth=True)
    if r["status"] != 200:
        raise RuntimeError(f"login({username}) failed with {r['status']}: {r['raw']}")
    return r["body"]["token"]


def get_server():
    global _server, _auth_token
    if _server is None:
        _server = _Server()
        atexit.register(_server.stop)
    # Reset the active token on every call, not just first init. Other modules
    # (auth conformance) point the module-scoped token at their own server; each
    # class re-binds it to the shared server's admin token in setUpClass.
    _auth_token = _server.token
    return _server


_SCALAR_SAMPLES = {
    "Text": "sample text",
    "Integer": 42,
    "Number": 3.14,
    "Boolean": True,
    "Date": "2026-05-19T00:00:00Z",
    "DateTime": "2026-05-19T12:00:00Z",
    "Time": "2026-05-19T12:00:00Z",
    "URL": "https://example.com/resource",
}


def _sample_one(spec):
    if spec["kind"] == "scalar":
        return _SCALAR_SAMPLES.get(spec["type"], "sample")
    if spec["kind"] == "enum":
        return spec["values"][0]
    if spec["kind"] == "embed":
        return {"@type": spec["type"], "alternateName": "en"}
    raise ValueError(f"_sample_one cannot handle kind {spec['kind']}")


def make_dep(server, entity):
    payload = build_payload(server, entity)
    r = request_json(server, "POST", "/" + _plural(entity), payload)
    if r["status"] != 201:
        raise RuntimeError(f"make_dep({entity}) failed with {r['status']}: {r['raw']}")
    return r["body"]["id"]


def _plural(entity):
    import re as _re
    return _re.sub(r"([A-Z])", r"-\1", entity).lstrip("-").lower() + "s"


def _unique_value(type_, base):
    # Gives each build a distinct value for a unique-key string field. Without
    # this every payload would carry the same sample value and the second create
    # in any multi-record test would trip duplicate detection. Ref key components
    # are already unique because each is freshly created per build.
    suffix = uuid.uuid4().hex
    return f"{base}/{suffix}" if type_ == "URL" else f"{base}-{suffix}"


def build_payload(server, entity, partial=False):
    # System and internal fields (READONLY_FIELDS) are never sent — they are not
    # client writable and would be rejected with 400.
    mod = MODELS[entity]
    key = set(mod.UNIQUE_KEY)
    payload = {}
    for name, spec in mod.FIELDS.items():
        if name in READONLY_FIELDS:
            continue
        if not partial and name not in mod.REQUIRED_FIELDS:
            continue
        if spec["kind"] == "ref":
            value = make_dep(server, spec["targets"][0])
        else:
            value = _sample_one(spec)
            if name in key and spec["kind"] == "scalar" and isinstance(value, str):
                value = _unique_value(spec["type"], value)
        payload[name] = [value] if spec["cardinality"] == "many" else value
    return payload


def post_entity(server, entity, payload):
    return request_json(server, "POST", "/" + _plural(entity), payload)


def request_json(server, method, path, body=None, headers=None, raw_body=None, no_auth=False):
    url = server.base_url + path
    data = None
    final_headers = {"Accept": "application/json"}
    # Attach the active bearer token unless opted out or the caller set their own
    # Authorization header (caller headers win on conflict).
    if not no_auth and _auth_token is not None:
        final_headers["Authorization"] = f"Bearer {_auth_token}"
    if raw_body is not None:
        data = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
        final_headers["Content-Type"] = "application/json"
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        final_headers["Content-Type"] = "application/json"
    if headers:
        final_headers.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=final_headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return {
                "status": r.status,
                "headers": {k.lower(): v for k, v in r.headers.items()},
                "body": json.loads(raw) if raw else None,
                "raw": raw.decode("utf-8", errors="replace") if raw else "",
            }
    except urllib.error.HTTPError as e:
        raw = e.read()
        return {
            "status": e.code,
            "headers": {k.lower(): v for k, v in e.headers.items()},
            "body": json.loads(raw) if raw else None,
            "raw": raw.decode("utf-8", errors="replace") if raw else "",
        }
