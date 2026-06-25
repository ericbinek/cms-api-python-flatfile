import unittest

from tests._helpers import start_server, request_json

BASE = "/blog-postings"


# Reads and writes have independent per-IP windows. Each test starts a server
# with one bucket set low and the other effectively unlimited, then drives
# requests until the limiter trips. Exact counts are not asserted — server
# startup spends a request or two (health probe, admin login) — only that
# limiting eventually engages after at least one request is admitted, and that
# the rejection carries the 429 envelope and a sane Retry-After header. Requests
# go out unauthenticated: the limiter runs before auth, so they still count.
class RateLimitTest(unittest.TestCase):
    def test_writes_over_limit_get_429_and_retry_after(self):
        server = start_server(env={"RATE_LIMIT_WRITE_PER_MINUTE": "5", "RATE_LIMIT_READ_PER_MINUTE": "1000000"})
        try:
            admitted = 0
            limited = None
            for _ in range(40):
                r = request_json(server, "POST", BASE, raw_body="{}", no_auth=True)
                if r["status"] == 429:
                    limited = r
                    break
                admitted += 1
            self.assertGreaterEqual(admitted, 1, "at least one write should be admitted before limiting")
            self.assertIsNotNone(limited, "writes should eventually be rate limited")
            retry_after = int(limited["headers"]["retry-after"])
            self.assertTrue(1 <= retry_after <= 60, f"Retry-After out of range: {limited['headers'].get('retry-after')}")
            self.assertEqual(limited["status"], 429)
            self.assertEqual(limited["body"]["error"], "TOO_MANY_REQUESTS")
        finally:
            server.stop()

    def test_reads_have_their_own_window(self):
        server = start_server(env={"RATE_LIMIT_READ_PER_MINUTE": "120", "RATE_LIMIT_WRITE_PER_MINUTE": "1000000"})
        try:
            admitted = 0
            limited = None
            for _ in range(200):
                r = request_json(server, "GET", BASE, no_auth=True)
                if r["status"] == 429:
                    limited = r
                    break
                admitted += 1
            self.assertGreaterEqual(admitted, 1, "at least one read should be admitted before limiting")
            self.assertIsNotNone(limited, "reads should eventually be rate limited")
            retry_after = int(limited["headers"]["retry-after"])
            self.assertTrue(1 <= retry_after <= 60)
            self.assertEqual(limited["status"], 429)
            self.assertEqual(limited["body"]["error"], "TOO_MANY_REQUESTS")
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
