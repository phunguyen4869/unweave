import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from unweave import tools


class LegacyDataDirTests(unittest.TestCase):
    """The app was SoundRazer Desktop up to 1.2.2; its data folder carries over."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.env = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.base)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temporary.cleanup()

    def test_legacy_folder_is_renamed_with_its_contents(self):
        legacy = self.base / tools.LEGACY_APP_NAME
        (legacy / "models").mkdir(parents=True)
        (legacy / "ui.json").write_text("{}", encoding="utf-8")
        tools.migrate_legacy_data_dir()
        self.assertFalse(legacy.exists())
        self.assertTrue((self.base / "Unweave" / "models").is_dir())
        self.assertTrue((self.base / "Unweave" / "ui.json").is_file())

    def test_existing_new_folder_is_left_alone(self):
        (self.base / tools.LEGACY_APP_NAME).mkdir()
        (self.base / "Unweave" / "models").mkdir(parents=True)
        tools.migrate_legacy_data_dir()
        self.assertTrue((self.base / tools.LEGACY_APP_NAME).is_dir())
        self.assertTrue((self.base / "Unweave" / "models").is_dir())

    def test_no_legacy_folder_is_a_no_op(self):
        tools.migrate_legacy_data_dir()
        self.assertFalse((self.base / "Unweave").exists())


if __name__ == "__main__":
    unittest.main()
