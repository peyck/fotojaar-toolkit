"""Tests voor het lokale servertje van de controle- en verhalenpagina, op elk besturingssysteem.
Uitvoeren:  python -m unittest discover tools/tests"""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build  # noqa: E402


class RevealCommand(unittest.TestCase):
    def run_reveal(self, system, path):
        with mock.patch.object(build.platform, "system", return_value=system), \
                mock.patch.object(build.subprocess, "Popen") as popen:
            build.reveal_in_file_manager(path)
        return popen.call_args[0][0]

    def test_windows(self):
        p = Path("C:/foto's/a b.jpg")
        self.assertEqual(self.run_reveal("Windows", p), ["explorer", "/select,", str(p)])

    def test_macos(self):
        p = Path("/Users/x/foto's/a b.jpg")
        self.assertEqual(self.run_reveal("Darwin", p), ["open", "-R", str(p)])

    def test_linux_opens_folder(self):
        p = Path("/home/x/foto's/a b.jpg")
        self.assertEqual(self.run_reveal("Linux", p), ["xdg-open", str(p.parent)])

    def test_names(self):
        for system, name in (("Windows", "Verkenner"), ("Darwin", "Finder"), ("Linux", "bestandsbeheer")):
            with mock.patch.object(build.platform, "system", return_value=system):
                self.assertEqual(build.file_manager_name(), name)


class Server(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.coll, self.data = base / "collectie", base / "data"
        (self.coll / "map met spatie").mkdir(parents=True)
        (self.data / "cache" / "thumbs").mkdir(parents=True)
        (self.coll / "map met spatie" / "foto één.jpg").write_bytes(b"jpg")
        (base / "geheim.txt").write_text("niet tonen")
        (self.data / "review.html").write_text("<script>const TOKEN = '__TOKEN__';</script>", encoding="utf-8")
        (self.data / "config.json").write_text('{"geheim": true}')
        (self.data / "cache" / "thumbs" / "a.jpg").write_bytes(b"thumb")
        self.patches = [mock.patch.object(build, "COLLECTION", self.coll), mock.patch.object(build, "DATA", self.data)]
        for p in self.patches:
            p.start()
        self.srv, self.token = build.make_server(self.data / "review.html", 0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def post_open(self, rp, token=None):
        h = {"Content-Type": "application/json"}
        if token is not None:
            h["X-Token"] = token
        return self.req("POST", "/open", json.dumps({"p": rp}).encode("utf-8"), h)

    def test_listens_on_localhost_only(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")

    def test_page_gets_token(self):
        status, body = self.req("GET", "/review.html")
        self.assertEqual(status, 200)
        self.assertIn(self.token, body.decode("utf-8"))
        self.assertNotIn("__TOKEN__", body.decode("utf-8"))

    def test_thumbnail_served_but_other_files_not(self):
        self.assertEqual(self.req("GET", "/cache/thumbs/a.jpg"), (200, b"thumb"))
        self.assertEqual(self.req("GET", "/config.json")[0], 404)
        self.assertEqual(self.req("GET", "/cache/thumbs/../../config.json")[0], 404)
        self.assertEqual(self.req("GET", "/%2e%2e/geheim.txt")[0], 404)

    def test_foreign_host_refused(self):
        self.assertEqual(self.req("GET", "/review.html", headers={"Host": "evil.example"})[0], 403)
        with mock.patch.object(build, "reveal_in_file_manager") as reveal:
            body = json.dumps({"p": "map met spatie/foto één.jpg"}).encode("utf-8")
            status, _ = self.req("POST", "/open", body, {"X-Token": self.token, "Host": "evil.example"})
            self.assertEqual(status, 403)
            reveal.assert_not_called()

    def test_open_needs_token(self):
        with mock.patch.object(build, "reveal_in_file_manager") as reveal:
            self.assertEqual(self.post_open("map met spatie/foto één.jpg")[0], 403)
            self.assertEqual(self.post_open("map met spatie/foto één.jpg", "fout")[0], 403)
            reveal.assert_not_called()

    def test_open_valid_file(self):
        with mock.patch.object(build, "reveal_in_file_manager") as reveal:
            status, _ = self.post_open("map met spatie/foto één.jpg", self.token)
        self.assertEqual(status, 200)
        reveal.assert_called_once_with(self.coll / "map met spatie" / "foto één.jpg")

    def test_open_refuses_outside_collection_and_missing(self):
        with mock.patch.object(build, "reveal_in_file_manager") as reveal:
            self.assertEqual(self.post_open("../geheim.txt", self.token)[0], 404)
            self.assertEqual(self.post_open("bestaat/niet.jpg", self.token)[0], 404)
            self.assertEqual(self.post_open("map met spatie", self.token)[0], 404)     # map, geen bestand
            reveal.assert_not_called()

    def test_open_only_on_open_path(self):
        self.assertEqual(self.req("POST", "/andere", b"{}", {"X-Token": self.token})[0], 403)


if __name__ == "__main__":
    unittest.main()
