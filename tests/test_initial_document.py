import json
import unittest
from html.parser import HTMLParser
from pathlib import Path

from backend.main import LiveSite, initial_document


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.scripts = []
        self.snapshot = ""
        self.in_snapshot = False
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            attrs = dict(attrs)
            self.scripts.append(attrs)
            self.in_snapshot = attrs.get("id") == "site-snapshot"

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_snapshot = False

    def handle_data(self, data):
        if self.in_snapshot:
            self.snapshot += data


class InitialDocumentTests(unittest.TestCase):
    def setUp(self):
        self.template = Path("frontend/index.html").read_text(encoding="utf-8")
        self.live = LiveSite(Path("."), Path("config.toml"))
        self.live.site = {
            "appearance": {"title": '标题 < & "', "kicker": "ACM", "description": '说明 " < &'},
            "sections": [
                {"title": "公开", "visibility": "public", "content": '</script><script>alert("x")</script>'},
                {"title": "管理", "visibility": "admin", "content": "private-content"},
            ],
        }

    def render(self, admin=False):
        data = self.live.payload(admin, "127.0.0.1")
        data["visit_count"] = 42
        source = initial_document(self.template, data)
        return source, Document(source), data

    def test_snapshot_escapes_script_termination_and_roundtrips(self):
        source, document, data = self.render()
        self.assertEqual(json.loads(document.snapshot), data)
        self.assertEqual(len(document.scripts), 4)
        self.assertNotIn('<script>alert', source)
        self.assertIn('<h1>标题 &lt; &amp; &quot;</h1>', source)
        self.assertIn('content="说明 &quot; &lt; &amp;"', source)

    def test_initial_html_uses_filtered_snapshot(self):
        public, _, _ = self.render()
        admin, _, _ = self.render(admin=True)
        self.assertNotIn("private-content", public)
        self.assertIn("private-content", admin)

    def test_missing_configuration_still_bootstraps(self):
        self.live.site = None
        self.live.error = "invalid config"
        source, document, data = self.render()
        self.assertEqual(json.loads(document.snapshot), data)
        self.assertNotIn('<header', source)
        self.assertTrue(data["stale"])


if __name__ == "__main__":
    unittest.main()
