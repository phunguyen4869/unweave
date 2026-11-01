"""Smoke tests for the reorganized Python package layout."""

import importlib.util
from pathlib import Path
import unittest

import unweave.webui as webui
import unweave.webui.server as server
import unweave.audio.pipeline
import unweave.projects as projects
import unweave.projects.metadata


class PackageLayoutTests(unittest.TestCase):
    def test_webui_exports(self):
        for name in ("serve", "make_server", "Library", "selection_stems"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(webui, name))

    def test_selection_stems(self):
        self.assertEqual(webui.selection_stems("vocals"), ["vocals", "instrumental"])
        for preset, stems in (("unknown", None), ("custom", None),
                              ("custom", ["not-a-stem"])):
            with self.subTest(preset=preset, stems=stems):
                with self.assertRaises(ValueError):
                    webui.selection_stems(preset, stems)

    def test_server_has_project_helpers(self):
        # Route handlers call these directly; a missing import used to turn every
        # upload into a 500 ("Unexpected server error").
        for name in ("import_project", "project_path", "describe_project", "save_metadata", "cover_path"):
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(server, name, None)))

    def test_static_assets(self):
        static = Path(server.__file__).resolve().parents[1] / "web"
        self.assertEqual(server.STATIC, static)
        for name in ("index.html", "js/app.js", "js/audio/trim.js", "js/audio/split.js",
                     "js/chrome/updates.js", "js/views/settings.js", "css/base.css"):
            with self.subTest(asset=name):
                self.assertTrue((static / name).is_file())

    def test_old_root_modules_are_gone(self):
        for name in ("ui", "pipeline", "guitar_split", "metadata_lookup", "setup"):
            with self.subTest(module=name):
                self.assertIsNone(importlib.util.find_spec(f"unweave.{name}"))

        # `unweave.projects` remains importable as the requested subpackage,
        # but the old projects.py module has been moved into projects/store.py.
        self.assertTrue(Path(projects.__file__).name == "__init__.py")
        self.assertFalse(Path(projects.__file__).with_name("projects.py").exists())


if __name__ == "__main__":
    unittest.main()
