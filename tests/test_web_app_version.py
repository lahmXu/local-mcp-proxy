import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_version import APP_VERSION, get_app_version
from models import ConfigStorage
from web_app import create_app


class WebAppVersionTest(unittest.TestCase):
    def test_source_version_is_available(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual("0.0.1", get_app_version())

    def test_environment_can_override_version(self):
        with patch.dict("os.environ", {"MCP_PROXY_VERSION": "9.8.7"}):
            self.assertEqual("9.8.7", get_app_version())

    def test_status_exposes_app_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(ConfigStorage(config_dir=Path(temp_dir)))
            app.config.update(TESTING=True)
            client = app.test_client()
            with client.session_transaction() as user_session:
                user_session["logged_in"] = True

            response = client.get("/api/status")

            self.assertEqual(200, response.status_code)
            self.assertEqual(APP_VERSION, response.get_json()["version"])

    def test_mysql_advanced_settings_are_collapsed_by_default(self):
        page = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('id="m_advanced_details"', page)
        self.assertNotIn('id="m_advanced_details" open', page)
        self.assertIn('id="appVersion"', page)


if __name__ == "__main__":
    unittest.main()
