"""Things that keep traffic to the wiki down: gzip and the one-time icon cache."""

import gzip
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from backend import db, http
from backend.ingest import icons

PNG = icons.PNG_MAGIC + b"data"


class GzipTest(unittest.TestCase):
    def _response(self, body: bytes, encoding: str | None):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = body
        response.headers = {"Content-Encoding": encoding} if encoding else {}
        return response

    def test_requests_and_decodes_gzip(self):
        payload = {"data": {"2": {"high": 250}}}
        compressed = gzip.compress(json.dumps(payload).encode())
        with mock.patch("urllib.request.urlopen", return_value=self._response(compressed, "gzip")) as urlopen:
            self.assertEqual(http.get_json("https://example.test/latest"), payload)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Accept-encoding"), "gzip")
        self.assertIn("osrs-gp-activity-finder", request.get_header("User-agent"))

    def test_plain_response(self):
        with mock.patch("urllib.request.urlopen", return_value=self._response(b'{"a": 1}', None)):
            self.assertEqual(http.get_json("https://example.test/x"), {"a": 1})


class IconTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.conn = db.connect(":memory:")
        self.conn.executemany("INSERT INTO items (id, name, members, icon) VALUES (?, ?, 0, ?)", [
            (1, "Ahrim's hood", "Ahrim's hood.png"),
            (2, "Coins", "Coins 10000.png"),
            (3, "Also coins", "Coins 10000.png"),  # shared icon: fetched once
            (4, "Gone", "Gone.png"),
            (5, "Weird", "Weird?.png"),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_filename_is_safe(self):
        self.assertEqual(icons.filename("Ahrim's hood.png"), "Ahrim's hood.png")
        self.assertEqual(icons.filename("../../etc/passwd"), "_.._etc_passwd.png")
        self.assertEqual(icons.filename("Weird?.png"), "Weird_.png")

    def test_downloads_each_icon_once(self):
        calls = []

        def fetch(url):
            calls.append(url)
            if "Gone" in url:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO())
            return b"<html>" if "Weird" in url else PNG

        stats = icons.download(self.conn, fetch=fetch, sleep=lambda _: None, directory=self.dir)
        self.assertEqual((stats["saved"], stats["failed"]), (2, 2))
        self.assertEqual(len(calls), 4)  # four distinct icons, the shared one only once
        self.assertIn("https://oldschool.runescape.wiki/images/Coins_10000.png", calls)
        self.assertEqual((self.dir / "Coins 10000.png").read_bytes(), PNG)
        self.assertFalse((self.dir / "Weird_.png").exists())  # not a PNG, not saved
        self.assertEqual(list(self.dir.glob("*.part")), [])

        calls.clear()
        icons.download(self.conn, fetch=fetch, sleep=lambda _: None, directory=self.dir)
        self.assertEqual(len(calls), 2)  # only the two that failed are retried

    def test_limit_and_pause(self):
        pauses = []
        icons.download(self.conn, limit=2, fetch=lambda url: PNG, sleep=pauses.append, directory=self.dir)
        self.assertEqual(len(pauses), 1)  # a pause between requests, not before the first
        self.assertEqual(len(icons.missing(self.conn, self.dir)), 2)


if __name__ == "__main__":
    unittest.main()
