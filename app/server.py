import json
import os
import sys
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

from app import http as cms_http
from app import errors as cms_errors
from app import auth as cms_auth
from app.models import account as account_model
from app.routers import auth as auth_router
from app.routers import blog_posting as blog_posting_router
from app.routers import person as person_router
from app.routers import web_page as web_page_router
from app.routers import image_object as image_object_router
from app.routers import category_code as category_code_router
from app.routers import category_code_set as category_code_set_router
from app.routers import defined_term as defined_term_router
from app.routers import defined_term_set as defined_term_set_router
from app.routers import comment as comment_router
from app.routers import web_site as web_site_router

ROUTERS = [
    blog_posting_router,
    person_router,
    web_page_router,
    image_object_router,
    category_code_router,
    category_code_set_router,
    defined_term_router,
    defined_term_set_router,
    comment_router,
    web_site_router,
]


class CmsHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self): self._dispatch()
    def do_POST(self): self._dispatch()
    def do_PUT(self): self._dispatch()
    def do_DELETE(self): self._dispatch()
    def do_OPTIONS(self): self._dispatch()
    # Route unsupported methods through _dispatch too, so they get the unified
    # error contract (TRACE/CONNECT -> 404, others -> 405) instead of the
    # BaseHTTPRequestHandler default of 501.
    def do_PATCH(self): self._dispatch()
    def do_TRACE(self): self._dispatch()
    def do_CONNECT(self): self._dispatch()

    def _dispatch(self):
        start = time.time()
        self._body_consumed = False
        url = urlparse(self.path)
        path = url.path
        method = self.command
        request_path = f"{method} {path}"
        try:
            if method in ("TRACE", "CONNECT"):
                cms_http.json_error(self, cms_errors.route_not_found(request_path))
                return
            if method == "OPTIONS":
                cms_http.preflight(self)
                return
            if method == "GET" and path == "/health":
                cms_http.json_response(self, 200, {"status": "ok"})
                return

            # Auth middleware: resolve the principal before routing. A presented
            # but invalid credential is 401; no credential is the anonymous one.
            principal = cms_auth.resolve_principal(self)

            if path == "/auth" or path.startswith("/auth/"):
                if auth_router.handle(self, method, path, url, request_path, principal):
                    return

            # Writes require a session — no role grants anonymous writes (401, not 403).
            if cms_auth.requires_session(method, principal):
                cms_http.json_error(self, cms_errors.unauthorized(request_path))
                return

            for router in ROUTERS:
                if router.handle(self, method, path, url, request_path, principal):
                    return
            cms_http.json_error(self, cms_errors.route_not_found(request_path))
        except cms_auth.UnauthorizedError:
            cms_http.json_error(self, cms_errors.unauthorized(request_path))
        except cms_http.BodyTooLargeError:
            cms_http.json_error(self, cms_errors.payload_too_large(request_path))
        except cms_http.UnsupportedMediaTypeError:
            cms_http.json_error(self, cms_errors.unsupported_media_type(request_path))
        except (json.JSONDecodeError, UnicodeDecodeError):
            cms_http.json_error(self, cms_errors.invalid_json(request_path))
        except Exception as e:
            print(f"[{request_path}] {e}", file=sys.stderr)
            cms_http.json_error(self, cms_errors.internal(request_path))
        finally:
            self._close_if_body_unread()
            ms = int((time.time() - start) * 1000)
            print(f"{method} {path} {self._last_status} {ms}ms", file=sys.stderr)

    def _close_if_body_unread(self):
        # A request body the handler never read (e.g. a 405 on PUT/POST that carries
        # a body) would otherwise stay in the socket buffer and corrupt the next
        # keep-alive request. Closing the connection keeps the protocol aligned.
        if self._body_consumed:
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        if length > 0:
            self.close_connection = True

    def log_message(self, format, *args):
        # Suppress default access log; _dispatch logs its own line.
        pass

    _last_status = 0

    def send_response_only(self, code, message=None):
        self._last_status = code
        super().send_response_only(code, message)


def main():
    port = int(os.environ.get("PORT", "3004"))
    host = os.environ.get("HOST", "0.0.0.0")
    # Bootstrap the first admin (if configured) before accepting requests.
    account_model.seed_admin()
    server = ThreadingHTTPServer((host, port), CmsHandler)
    print(f"CMS API running at http://{host}:{port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("Server closed.", file=sys.stderr)
