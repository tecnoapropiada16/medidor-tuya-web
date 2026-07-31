import os
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta

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

    def test_force_registration_allows_immediate_record_after_restart(self):
        sys.modules.pop("app", None)
        import app

        ahora = datetime.now()
        ultimo_ts = (ahora - timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S")
        datos_existentes = [{"timestamp": ultimo_ts, "energia_consumida_wh": 100.0, "energia_inyectada_wh": 10.0}]

        self.assertTrue(app.deberia_guardar_nuevo_registro(datos_existentes, ahora, 110.0, 10.0, fuerza_registro=True))
        self.assertTrue(app.deberia_guardar_nuevo_registro(datos_existentes, ahora, 105.0, 10.0, fuerza_registro=False, nube_actuales=[]))
        self.assertFalse(app.deberia_guardar_nuevo_registro(datos_existentes, ahora, 105.0, 10.0, fuerza_registro=False, nube_actuales=[{"timestamp": "x"}]))


if __name__ == "__main__":
    unittest.main()
