import unittest

from tests._helpers import build_payload, get_server, request_json

ENTITY = "DefinedTerm"
BASE = "/defined-terms"


class DefinedTermApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = get_server()

    def _create(self):
        payload = build_payload(self.server, ENTITY)
        r = request_json(self.server, "POST", BASE, payload)
        if r["status"] != 201:
            raise AssertionError(f"POST {BASE} expected 201, got {r['status']}: {r['raw']}")
        return r["body"]

    def test_create_returns_201_with_type_and_id(self):
        item = self._create()
        self.assertEqual(item["@type"], ENTITY)
        self.assertEqual(item["@context"], "https://schema.org")
        self.assertTrue(item.get("id"))

    def test_get_by_id_returns_200_with_etag(self):
        item = self._create()
        r = request_json(self.server, "GET", f"{BASE}/{item['id']}")
        self.assertEqual(r["status"], 200)
        self.assertTrue(r["headers"].get("etag"))

    def test_list_returns_items_total_envelope(self):
        self._create()
        r = request_json(self.server, "GET", BASE)
        self.assertEqual(r["status"], 200)
        self.assertIsInstance(r["body"].get("items"), list)
        self.assertIsInstance(r["body"].get("total"), int)

    def test_put_partial_update_returns_200(self):
        item = self._create()
        partial = build_payload(self.server, ENTITY, partial=True)
        r = request_json(self.server, "PUT", f"{BASE}/{item['id']}", partial)
        self.assertEqual(r["status"], 200, f"PUT expected 200, got {r['status']}: {r['raw']}")

    def test_delete_returns_204_then_404(self):
        item = self._create()
        d = request_json(self.server, "DELETE", f"{BASE}/{item['id']}")
        self.assertEqual(d["status"], 204)
        g = request_json(self.server, "GET", f"{BASE}/{item['id']}")
        self.assertEqual(g["status"], 404)

    def test_invalid_uuid_returns_400_invalid_id(self):
        r = request_json(self.server, "GET", f"{BASE}/not-a-uuid")
        self.assertEqual(r["status"], 400)
        self.assertEqual(r["body"]["error"], "INVALID_ID")

    def test_unknown_id_returns_404_not_found(self):
        r = request_json(self.server, "GET", f"{BASE}/00000000-0000-0000-0000-000000000000")
        self.assertEqual(r["status"], 404)
        self.assertEqual(r["body"]["error"], "NOT_FOUND")

    def test_pagination_limit_offset_honour_total(self):
        self._create()
        self._create()
        self._create()
        r = request_json(self.server, "GET", f"{BASE}?limit=2&offset=0")
        self.assertGreaterEqual(r["body"]["total"], 3)
        self.assertLessEqual(len(r["body"]["items"]), 2)

    def test_sort_by_name_accepted(self):
        r = request_json(self.server, "GET", f"{BASE}?sort=name&order=asc")
        self.assertEqual(r["status"], 200)

    def test_unknown_sort_field_rejected_with_400(self):
        r = request_json(self.server, "GET", f"{BASE}?sort=definitely-not-a-field")
        self.assertEqual(r["status"], 400)


    def test_filter_on_text_field_name_returns_matches(self):
        created = self._create()
        needle = str(created.get("name", ""))[:4]
        if not needle:
            return
        from urllib.parse import quote
        r = request_json(self.server, "GET", f"{BASE}?name={quote(needle)}")
        found = any(i.get("id") == created["id"] for i in r["body"]["items"])
        self.assertTrue(found, "created item not found via filter")

    def test_stale_if_match_on_put_returns_412(self):
        item = self._create()
        r = request_json(self.server, "PUT", f"{BASE}/{item['id']}", {}, headers={"If-Match": '"0000000000000000"'})
        self.assertEqual(r["status"], 412)

    def test_cors_preflight_returns_204_with_allow_headers(self):
        r = request_json(self.server, "OPTIONS", BASE, headers={"Origin": "https://example.com", "Access-Control-Request-Method": "POST"})
        self.assertEqual(r["status"], 204)
        self.assertEqual(r["headers"].get("access-control-allow-origin"), "*")

    def test_deeply_nested_json_body_rejected_with_400(self):
        depth = 2000
        deep = "[" * depth + "]" * depth
        r = request_json(self.server, "POST", BASE, raw_body=deep)
        self.assertEqual(r["status"], 400)
        self.assertEqual(r["body"]["error"], "INVALID_JSON")

    def test_get_by_id_embeds_in_defined_term_set_object_list_stays_flat(self):
        payload = build_payload(self.server, ENTITY, partial=True)
        created = request_json(self.server, "POST", BASE, payload)["body"]

        # POST response keeps refs flat (UUID strings).
        ref_id = created["inDefinedTermSet"]
        self.assertIsInstance(ref_id, str)

        # Single-resource GET embeds the referenced entity one level deep.
        got = request_json(self.server, "GET", f"{BASE}/{created['id']}")["body"]
        embedded = got["inDefinedTermSet"]
        self.assertIsInstance(embedded, dict)
        self.assertEqual(embedded["@type"], "DefinedTermSet")
        self.assertEqual(embedded["id"], ref_id)

        # List responses stay flat — refs remain UUID strings.
        listed = request_json(self.server, "GET", f"{BASE}?limit=100")["body"]
        in_list = next(i for i in listed["items"] if i["id"] == created["id"])
        self.assertIsInstance(in_list["inDefinedTermSet"], str)

    def test_get_by_id_leaves_dangling_in_defined_term_set_ref_as_uuid(self):
        dangling = "00000000-0000-0000-0000-000000000000"
        payload = build_payload(self.server, ENTITY, partial=True)
        payload["inDefinedTermSet"] = dangling
        created = request_json(self.server, "POST", BASE, payload)["body"]
        got = request_json(self.server, "GET", f"{BASE}/{created['id']}")["body"]
        self.assertEqual(got["inDefinedTermSet"], dangling)


if __name__ == "__main__":
    unittest.main()
