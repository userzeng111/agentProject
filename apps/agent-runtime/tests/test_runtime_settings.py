import tempfile
import unittest
from pathlib import Path

from app.settings import runtime_settings


class RuntimeSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_path = runtime_settings._RUNTIME_SETTINGS_PATH

    def tearDown(self) -> None:
        runtime_settings._RUNTIME_SETTINGS_PATH = self._original_path

    def test_protocol_override_does_not_overwrite_corrupted_settings_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "runtime_settings.json"
            settings_path.write_text("{ broken json", encoding="utf-8")
            runtime_settings._RUNTIME_SETTINGS_PATH = settings_path

            with self.assertRaises(RuntimeError):
                runtime_settings.set_model_protocol_override("K2.6", "anthropic")

            self.assertEqual(settings_path.read_text(encoding="utf-8"), "{ broken json")


if __name__ == "__main__":
    unittest.main()
