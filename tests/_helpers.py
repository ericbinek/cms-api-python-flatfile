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
from pathlib import Path

from app.models import blog_posting as _blog_posting_mod
from app.models import person as _person_mod
from app.models import web_page as _web_page_mod
from app.models import image_object as _image_object_mod
from app.models import category_code as _category_code_mod
from app.models import category_code_set as _category_code_set_mod
from app.models import defined_term as _defined_term_mod
from app.models import defined_term_set as _defined_term_set_mod
from app.models import comment as _comment_mod
from app.models import web_site as _web_site_mod

MODELS = {
    "BlogPosting": _blog_posting_mod,
    "Person": _person_mod,
    "WebPage": _web_page_mod,
    "ImageObject": _image_object_mod,
    "CategoryCode": _category_code_mod,
    "CategoryCodeSet": _category_code_set_mod,
    "DefinedTerm": _defined_term_mod,
    "DefinedTermSet": _defined_term_set_mod,
    "Comment": _comment_mod,
    "WebSite": _web_site_mod,
}

REPO_ROOT = Path(__file__).resolve().parents[1]

_server = None


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
    def __init__(self):
        self.port = _free_port()
        self.data_dir = tempfile.mkdtemp(prefix="cms-test-py-")
        env = {**os.environ, "PORT": str(self.port), "DATA_DIR": self.data_dir, "PYTHONPATH": str(REPO_ROOT)}
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "app"],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._wait_for_health()

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


def get_server():
    global _server
    if _server is None:
        _server = _Server()
        atexit.register(_server.stop)
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


def build_payload(server, entity, partial=False):
    mod = MODELS[entity]
    payload = {}
    for name, spec in mod.FIELDS.items():
        if not partial and name not in mod.REQUIRED_FIELDS:
            continue
        if spec["kind"] == "ref":
            value = make_dep(server, spec["targets"][0])
        else:
            value = _sample_one(spec)
        payload[name] = [value] if spec["cardinality"] == "many" else value
    return payload


def request_json(server, method, path, body=None, headers=None, raw_body=None):
    url = server.base_url + path
    data = None
    final_headers = {"Accept": "application/json"}
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
