"""Acquiring fifty documents from a handful of hosts must not read as an attack."""
import unittest
import urllib.error
from email.message import Message
from unittest import mock

from scripts import bro_acquire_knowledge as acquire


def http_error(code, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError("https://example.test/doc", code, "no", headers, None)


class Response:
    def __init__(self, payload=b"a document long enough to be one"):
        self.payload = payload
        self.headers = Message()
        self.headers["Content-Type"] = "text/plain"

    def read(self, _limit):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class AcquisitionPacingTests(unittest.TestCase):
    def setUp(self):
        acquire._LAST_REQUEST.clear()
        self.waited = []

    def wait(self, seconds):
        self.waited.append(seconds)

    def test_a_second_request_to_the_same_host_waits(self):
        # first call reads 0.0; second reads 0.2, waits the remainder, then re-reads 1.5
        clock = iter([0.0, 0.2, 1.5])
        acquire._pace("example.test", now=lambda: next(clock), wait=self.wait)
        acquire._pace("example.test", now=lambda: next(clock), wait=self.wait)
        self.assertEqual(len(self.waited), 1)
        self.assertAlmostEqual(self.waited[0], acquire.HOST_INTERVAL_SECONDS - 0.2)

    def test_a_different_host_is_not_made_to_wait(self):
        clock = iter([0.0, 0.0])
        acquire._pace("one.test", now=lambda: next(clock), wait=self.wait)
        acquire._pace("two.test", now=lambda: next(clock), wait=self.wait)
        self.assertEqual(self.waited, [])

    def test_a_rate_limited_page_is_retried_and_succeeds(self):
        """The two OWASP pages that failed the first production acquisition served fine later."""
        answers = [http_error(429), Response()]

        def urlopen(_request, timeout=None):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        with mock.patch.object(acquire.urllib.request, "urlopen", urlopen):
            payload, content_type = acquire.fetch("https://example.test/doc", wait=self.wait)
        self.assertEqual(content_type, "text/plain")
        self.assertTrue(payload)
        self.assertEqual(answers, [])

    def test_a_servers_own_retry_after_is_honoured_and_capped(self):
        with mock.patch.object(acquire.urllib.request, "urlopen",
                               mock.Mock(side_effect=http_error(429, retry_after=9))):
            with self.assertRaises(acquire.AcquisitionRejected):
                acquire.fetch("https://example.test/doc", wait=self.wait)
        self.assertIn(9.0, self.waited)
        self.assertTrue(all(seconds <= acquire.MAX_RETRY_WAIT_SECONDS for seconds in self.waited))

    def test_an_absurd_retry_after_cannot_stall_acquisition(self):
        with mock.patch.object(acquire.urllib.request, "urlopen",
                               mock.Mock(side_effect=http_error(503, retry_after=86400))):
            with self.assertRaises(acquire.AcquisitionRejected):
                acquire.fetch("https://example.test/doc", wait=self.wait)
        self.assertTrue(all(seconds <= acquire.MAX_RETRY_WAIT_SECONDS for seconds in self.waited))

    def test_a_permanent_refusal_is_not_retried(self):
        urlopen = mock.Mock(side_effect=http_error(404))
        with mock.patch.object(acquire.urllib.request, "urlopen", urlopen):
            with self.assertRaises(acquire.AcquisitionRejected) as raised:
                acquire.fetch("https://example.test/doc", wait=self.wait)
        self.assertIn("404", str(raised.exception))
        self.assertEqual(urlopen.call_count, 1)

    def test_retrying_is_bounded(self):
        urlopen = mock.Mock(side_effect=http_error(429))
        with mock.patch.object(acquire.urllib.request, "urlopen", urlopen):
            with self.assertRaises(acquire.AcquisitionRejected):
                acquire.fetch("https://example.test/doc", wait=self.wait)
        self.assertEqual(urlopen.call_count, acquire.MAX_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
