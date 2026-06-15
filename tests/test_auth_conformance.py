import unittest

from tests._helpers import build_payload, login, post_entity, request_json, set_auth_token, start_server

# Five accounts cover the matrix, ownership and the workflow roles.
ACCOUNTS = [
    {"username": "admin", "password": "pw-admin", "role": "admin"},
    {"username": "editor", "password": "pw-editor", "role": "editor"},
    {"username": "author", "password": "pw-author", "role": "author"},
    {"username": "author2", "password": "pw-author2", "role": "author"},
    {"username": "viewer", "password": "pw-viewer", "role": "viewer"},
]


def _req(server, bearer, method, path, body=None):
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else None
    return request_json(server, method, path, body, headers=headers, no_auth=True)


class AuthConformanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = start_server(accounts=ACCOUNTS)
        cls.token = {a["username"]: login(cls.server, a["username"], a["password"]) for a in ACCOUNTS}

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    # Create through the public API as a given role, returning the response.
    def _create_as(self, bearer, entity, base, overrides=None):
        # Dependencies (refs) are built as admin via the module token.
        set_auth_token(self.token["admin"])
        payload = build_payload(self.server, entity)
        if overrides:
            payload.update(overrides)
        return _req(self.server, bearer, "POST", base, payload)

    # --- Authentication ---------------------------------------------------

    def test_login_returns_token_account_expiry(self):
        r = _req(self.server, None, "POST", "/auth/login", {"username": "admin", "password": "pw-admin"})
        self.assertEqual(r["status"], 200)
        body = r["body"]
        self.assertIsInstance(body["token"], str)
        self.assertEqual(body["account"]["username"], "admin")
        self.assertEqual(body["account"]["role"], "admin")
        self.assertTrue(body["account"]["id"])
        self.assertTrue(body["expiresAt"])
        self.assertNotIn("passwordHash", body["account"])

    def test_login_wrong_password_401(self):
        r = _req(self.server, None, "POST", "/auth/login", {"username": "admin", "password": "wrong"})
        self.assertEqual(r["status"], 401)
        self.assertEqual(r["body"]["error"], "UNAUTHORIZED")

    def test_login_unknown_user_same_401(self):
        r = _req(self.server, None, "POST", "/auth/login", {"username": "ghost", "password": "whatever"})
        self.assertEqual(r["status"], 401)
        self.assertEqual(r["body"]["error"], "UNAUTHORIZED")

    def test_login_missing_fields_400(self):
        r = _req(self.server, None, "POST", "/auth/login", {"username": "admin"})
        self.assertEqual(r["status"], 400)
        self.assertEqual(r["body"]["error"], "VALIDATION_ERROR")

    def test_me_with_valid_token_returns_account(self):
        r = _req(self.server, self.token["author"], "GET", "/auth/me")
        self.assertEqual(r["status"], 200)
        body = r["body"]
        self.assertEqual(body["account"]["username"], "author")
        self.assertEqual(body["account"]["role"], "author")
        self.assertNotIn("passwordHash", body["account"])

    def test_me_without_token_401(self):
        r = _req(self.server, None, "GET", "/auth/me")
        self.assertEqual(r["status"], 401)

    def test_me_with_invalid_token_401(self):
        r = _req(self.server, "not-a-real-token", "GET", "/auth/me")
        self.assertEqual(r["status"], 401)

    def test_logout_invalidates_session_immediately(self):
        fresh = login(self.server, "viewer", "pw-viewer")
        out = _req(self.server, fresh, "POST", "/auth/logout")
        self.assertEqual(out["status"], 204)
        reuse = _req(self.server, fresh, "GET", "/auth/me")
        self.assertEqual(reuse["status"], 401)
        again = _req(self.server, fresh, "POST", "/auth/logout")
        self.assertEqual(again["status"], 401)

    def test_logout_without_token_401(self):
        r = _req(self.server, None, "POST", "/auth/logout")
        self.assertEqual(r["status"], 401)

    # --- Authorization (type-level) ---------------------------------------

    def test_write_without_session_is_401_not_403(self):
        set_auth_token(self.token["admin"])
        payload = build_payload(self.server, "BlogPosting")
        r = _req(self.server, None, "POST", "/blog-postings", payload)
        self.assertEqual(r["status"], 401)

    def test_viewer_may_read_but_not_write(self):
        created = self._create_as(self.token["admin"], "BlogPosting", "/blog-postings")
        item = created["body"]
        self.assertEqual(_req(self.server, self.token["viewer"], "GET", f"{"/blog-postings"}/{item['id']}")["status"], 200)
        self.assertEqual(self._create_as(self.token["viewer"], "BlogPosting", "/blog-postings")["status"], 403)
        self.assertEqual(_req(self.server, self.token["viewer"], "PUT", f"{"/blog-postings"}/{item['id']}", {})["status"], 403)
        self.assertEqual(_req(self.server, self.token["viewer"], "DELETE", f"{"/blog-postings"}/{item['id']}")["status"], 403)

    def test_author_create_editor_admin_full_crud(self):
        self.assertEqual(self._create_as(self.token["author"], "BlogPosting", "/blog-postings")["status"], 201)
        self.assertEqual(self._create_as(self.token["editor"], "BlogPosting", "/blog-postings")["status"], 201)
        self.assertEqual(self._create_as(self.token["admin"], "BlogPosting", "/blog-postings")["status"], 201)

    # --- Ownership --------------------------------------------------------

    def test_created_by_and_author_owns_only_own(self):
        mine = self._create_as(self.token["author"], "BlogPosting", "/blog-postings")["body"]
        theirs = self._create_as(self.token["author2"], "BlogPosting", "/blog-postings")["body"]

        own_update = _req(self.server, self.token["author"], "PUT", f"{"/blog-postings"}/{mine['id']}", {})
        self.assertEqual(own_update["status"], 200)
        self.assertEqual(_req(self.server, self.token["author"], "PUT", f"{"/blog-postings"}/{theirs['id']}", {})["status"], 403)
        self.assertEqual(_req(self.server, self.token["author"], "DELETE", f"{"/blog-postings"}/{theirs['id']}")["status"], 403)

        # Editor and admin modify any record regardless of ownership.
        self.assertEqual(_req(self.server, self.token["editor"], "PUT", f"{"/blog-postings"}/{theirs['id']}", {})["status"], 200)
        self.assertEqual(_req(self.server, self.token["admin"], "DELETE", f"{"/blog-postings"}/{mine['id']}")["status"], 204)

    # --- Field-level ------------------------------------------------------

    def test_created_by_never_in_response(self):
        created = self._create_as(self.token["admin"], "BlogPosting", "/blog-postings")["body"]
        self.assertNotIn("createdBy", created)
        got = _req(self.server, self.token["admin"], "GET", f"{"/blog-postings"}/{created['id']}")["body"]
        self.assertNotIn("createdBy", got)
        listed = _req(self.server, self.token["admin"], "GET", f"{"/blog-postings"}?limit=100")["body"]
        for item in listed["items"]:
            self.assertNotIn("createdBy", item)

    def test_system_internal_fields_rejected_in_write(self):
        set_auth_token(self.token["admin"])
        for field in ["id", "dateCreated", "dateModified", "createdBy"]:
            payload = build_payload(self.server, "BlogPosting")
            payload[field] = "00000000-0000-0000-0000-000000000000" if field == "id" else "x"
            r = _req(self.server, self.token["admin"], "POST", "/blog-postings", payload)
            self.assertEqual(r["status"], 400, f"expected 400 for field {field}, got {r['status']}")
            self.assertEqual(r["body"]["error"], "VALIDATION_ERROR")

    def test_server_managed_fields_in_output(self):
        created = self._create_as(self.token["admin"], "BlogPosting", "/blog-postings")["body"]
        self.assertTrue(created["id"])
        self.assertTrue(created["dateCreated"])
        self.assertTrue(created["dateModified"])

    # --- Publication workflow ---------------------------------------------

    def test_fresh_record_has_initial_status(self):
        created = self._create_as(self.token["author"], "BlogPosting", "/blog-postings")["body"]
        self.assertEqual(created["creativeWorkStatus"], "Draft")

    def test_author_initial_transition_but_not_editor_only(self):
        item = self._create_as(self.token["author"], "BlogPosting", "/blog-postings")["body"]
        a = _req(self.server, self.token["author"], "PUT", f"{"/blog-postings"}/{item['id']}", {"creativeWorkStatus": "Pending"})
        self.assertEqual(a["status"], 200)
        self.assertEqual(a["body"]["creativeWorkStatus"], "Pending")
        b = _req(self.server, self.token["author"], "PUT", f"{"/blog-postings"}/{item['id']}", {"creativeWorkStatus": "Published"})
        self.assertEqual(b["status"], 403)
        c = _req(self.server, self.token["editor"], "PUT", f"{"/blog-postings"}/{item['id']}", {"creativeWorkStatus": "Published"})
        self.assertEqual(c["status"], 200)

    def test_unmodelled_transition_forbidden(self):
        item = self._create_as(self.token["editor"], "BlogPosting", "/blog-postings")["body"]
        r = _req(self.server, self.token["editor"], "PUT", f"{"/blog-postings"}/{item['id']}", {"creativeWorkStatus": "Published"})
        self.assertEqual(r["status"], 403)

    # --- Anonymous visibility (public) ------------------------------------

    def test_anonymous_sees_only_public_non_public_detail_404(self):
        item = self._create_as(self.token["admin"], "BlogPosting", "/blog-postings")["body"]

        hidden_list = _req(self.server, None, "GET", f"{"/blog-postings"}?limit=100")["body"]
        self.assertFalse(any(i["id"] == item["id"] for i in hidden_list["items"]))
        self.assertEqual(_req(self.server, None, "GET", f"{"/blog-postings"}/{item['id']}")["status"], 404)

        _req(self.server, self.token["admin"], "PUT", f"{"/blog-postings"}/{item['id']}", {"creativeWorkStatus": "Pending"})
        publish = {"creativeWorkStatus": "Published"}
        publish["datePublished"] = "2020-01-01T00:00:00Z"
        pub = _req(self.server, self.token["admin"], "PUT", f"{"/blog-postings"}/{item['id']}", publish)
        self.assertEqual(pub["status"], 200)

        shown_list = _req(self.server, None, "GET", f"{"/blog-postings"}?limit=100")["body"]
        self.assertTrue(any(i["id"] == item["id"] for i in shown_list["items"]))
        detail = _req(self.server, None, "GET", f"{"/blog-postings"}/{item['id']}")
        self.assertEqual(detail["status"], 200)
        self.assertNotIn("createdBy", detail["body"])


    def test_plain_entity_anonymously_readable_no_workflow(self):
        created = self._create_as(self.token["admin"], "Person", "/persons")["body"]
        anon = _req(self.server, None, "GET", f"{"/persons"}/{created['id']}")
        self.assertEqual(anon["status"], 200)
        upd = _req(self.server, self.token["editor"], "PUT", f"{"/persons"}/{created['id']}", {})
        self.assertEqual(upd["status"], 200)


    # --- Bootstrap --------------------------------------------------------

    def test_empty_store_plus_env_seeds_admin(self):
        s = start_server(env={"ADMIN_USER": "root", "ADMIN_PASSWORD": "root-pw"})
        try:
            t = login(s, "root", "root-pw")
            self.assertIsInstance(t, str)
        finally:
            s.stop()

    def test_non_empty_store_makes_env_seed_noop(self):
        s = start_server(accounts=ACCOUNTS, env={"ADMIN_USER": "ghost", "ADMIN_PASSWORD": "ghost-pw"})
        try:
            direct = _req(s, None, "POST", "/auth/login", {"username": "ghost", "password": "ghost-pw"})
            self.assertEqual(direct["status"], 401)
        finally:
            s.stop()

    def test_empty_store_without_env_grants_no_one(self):
        s = start_server(accounts=[])
        try:
            payload = build_payload(self.server, "BlogPosting")
            r = _req(s, None, "POST", "/blog-postings", payload)
            self.assertEqual(r["status"], 401)
        finally:
            s.stop()


if __name__ == "__main__":
    unittest.main()
