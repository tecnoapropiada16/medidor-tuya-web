import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestPathResolution(unittest.TestCase):
    def test_workspace_files_use_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            old_cwd = os.getcwd()
            os.chdir(tmp_dir)
            try:
                sys.modules.pop("app", None)
                import app

                self.assertTrue(os.path.isabs(app.CONFIG_FILE))
                self.assertTrue(os.path.isabs(app.DATA_FILE))
                self.assertEqual(Path(app.CONFIG_FILE).resolve(), (ROOT / "config_persistent.json").resolve())
                self.assertEqual(Path(app.DATA_FILE).resolve(), (ROOT / "datos_monitoreo.json").resolve())
            finally:
                os.chdir(old_cwd)
                sys.modules.pop("app", None)


if __name__ == "__main__":
    unittest.main()
