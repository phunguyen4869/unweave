"""In-app update check (spec 10): version compare, consent prefs, no surprise network."""

import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from unweave.updates import (ASK_AGAIN_S, CHECK_INTERVAL_S, fetch_latest_release, is_newer,
                             normalize_tag, version_tuple)
from unweave.webui.library import Library


class VersionCompareTests(unittest.TestCase):
    def test_normalize_strips_v(self):
        self.assertEqual(normalize_tag("v1.3.1"), "1.3.1")
        self.assertEqual(normalize_tag("1.3.1"), "1.3.1")

    def test_tuple_orders_semver(self):
        self.assertLess(version_tuple("1.3.1"), version_tuple("1.4.0"))
        self.assertLess(version_tuple("1.9.0"), version_tuple("1.10.0"))
        self.assertEqual(version_tuple("v1.3.1"), version_tuple("1.3.1"))

    def test_is_newer(self):
        self.assertTrue(is_newer("1.4.0", "1.3.1"))
        self.assertFalse(is_newer("1.3.1", "1.3.1"))
        self.assertFalse(is_newer("1.2.0", "1.3.1"))
        self.assertFalse(is_newer("", "1.3.1"))


class FetchLatestTests(unittest.TestCase):
    def test_parses_stable_release(self):
        payload = json.dumps({
            "tag_name": "v1.4.0",
            "html_url": "https://github.com/um1chc5/unweave/releases/tag/v1.4.0",
            "name": "1.4.0",
            "draft": False,
            "prerelease": False,
        }).encode()

        def opener(_request):
            return io.BytesIO(payload)

        release = fetch_latest_release("Unweave/test", opener=opener)
        self.assertEqual(release["tag"], "1.4.0")
        self.assertIn("releases/tag", release["url"])

    def test_rejects_prerelease_payload(self):
        payload = json.dumps({
            "tag_name": "v2.0.0-beta",
            "html_url": "https://example.test",
            "draft": False,
            "prerelease": True,
        }).encode()

        def opener(_request):
            return io.BytesIO(payload)

        with self.assertRaises(ValueError):
            fetch_latest_release("Unweave/test", opener=opener)


class UpdatesPrefsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.config = base / "ui.json"
        self.cache = base / "cache"
        self.root = base / "projects"
        self.root.mkdir()
        self.library = Library(self.root, self.config, self.cache, default_root=self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_default_status_wants_prompt_and_no_auto_check(self):
        status = self.library.updates_status()
        self.assertEqual(status["check"], "ask")
        self.assertTrue(status["should_prompt"])
        self.assertFalse(status["should_auto_check"])
        self.assertFalse(status["available"])

    def test_allow_enables_auto_check(self):
        status = self.library.set_updates_prefs({"check": "auto"})
        self.assertEqual(status["check"], "auto")
        self.assertTrue(status["should_auto_check"])
        self.assertFalse(status["should_prompt"])

    def test_not_now_dont_ask_is_manual_only(self):
        status = self.library.set_updates_prefs({"check": "manual"})
        self.assertEqual(status["check"], "manual")
        self.assertFalse(status["should_prompt"])
        self.assertFalse(status["should_auto_check"])

    def test_not_now_ask_again_defers_prompt(self):
        status = self.library.set_updates_prefs({"check": "ask", "ask_again_in": ASK_AGAIN_S})
        self.assertEqual(status["check"], "ask")
        self.assertFalse(status["should_prompt"])
        self.assertGreater(status["ask_again_at"], time.time())

    def test_set_root_keeps_update_prefs(self):
        self.library.set_updates_prefs({"check": "auto"})
        other = self.root / "other"
        other.mkdir()
        self.library.set_root(str(other))
        saved = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(saved["root"], str(other.resolve()))
        self.assertEqual(saved["updates"]["check"], "auto")

    def test_manual_check_fetches_and_marks_available(self):
        self.library.set_updates_prefs({"check": "manual"})
        payload = json.dumps({
            "tag_name": "9.9.9",
            "html_url": "https://github.com/um1chc5/unweave/releases/tag/9.9.9",
            "name": "9.9.9",
            "draft": False,
            "prerelease": False,
        }).encode()

        def opener(_request):
            return io.BytesIO(payload)

        with mock.patch("unweave.webui.library.APP_VERSION", "1.3.1"):
            status = self.library.check_updates(manual=True, opener=opener)
        self.assertTrue(status["available"])
        self.assertEqual(status["latest"], "9.9.9")
        self.assertIsNotNone(status["last_checked_at"])

    def test_auto_check_skipped_when_manual_mode(self):
        self.library.set_updates_prefs({"check": "manual"})
        called = {"n": 0}

        def opener(_request):
            called["n"] += 1
            raise AssertionError("must not hit the network")

        status = self.library.check_updates(manual=False, opener=opener)
        self.assertEqual(called["n"], 0)
        self.assertEqual(status["check"], "manual")

    def test_auto_check_throttled_within_interval(self):
        self.library.set_updates_prefs({"check": "auto"})
        cfg = self.library._updates_section()
        cfg["last_checked_at"] = time.time()
        cfg["latest_tag"] = "1.3.1"
        self.library._write_updates(cfg)
        called = {"n": 0}

        def opener(_request):
            called["n"] += 1
            raise AssertionError("throttled auto check must not fetch")

        status = self.library.check_updates(manual=False, opener=opener)
        self.assertEqual(called["n"], 0)
        self.assertFalse(status["should_auto_check"])
        self.assertLess(time.time() - status["last_checked_at"], CHECK_INTERVAL_S)

    def test_dismissed_tag_hides_available(self):
        self.library.set_updates_prefs({"check": "auto"})
        cfg = self.library._updates_section()
        cfg["latest_tag"] = "9.9.9"
        cfg["dismissed_tag"] = "9.9.9"
        self.library._write_updates(cfg)
        with mock.patch("unweave.webui.library.APP_VERSION", "1.3.1"):
            status = self.library.updates_status()
        self.assertFalse(status["available"])


if __name__ == "__main__":
    unittest.main()
