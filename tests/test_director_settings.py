"""Application configuration precedence and credential handling contracts."""

import os
import tempfile
import unittest
from contextlib import chdir
from pathlib import Path
from unittest.mock import patch

from pydantic import SecretStr, ValidationError

from app.director.settings import DirectorSettings


class DirectorSettingsTests(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_local_configuration_is_overridden_by_environment_then_explicit_values(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory, chdir(directory):
            environment_file = Path(directory) / ".env"
            environment_file.write_text(
                "GEMINI_API_KEY=local-key\nGEMINI_MODEL=local-model\n"
                "MOTIONBRICKS_PORT=6100\nOTHER_APPLICATION_OPTION=ignored\n"
            )
            local = DirectorSettings()
            self.assertEqual(local.require_api_key(), "local-key")
            self.assertEqual((local.gemini_model, local.port), ("local-model", 6100))
            with patch.dict(
                os.environ,
                {
                    "GEMINI_API_KEY": "host-key",
                    "GEMINI_MODEL": "host-model",
                    "MOTIONBRICKS_PORT": "6200",
                },
            ):
                hosted = DirectorSettings(_env_file=environment_file)
                explicit = DirectorSettings(
                    _env_file=environment_file,
                    gemini_api_key=SecretStr("stdin-key"),
                    gemini_model="cli-model",
                    port=6300,
                )
            self.assertEqual(hosted.require_api_key(), "host-key")
            self.assertEqual((hosted.gemini_model, hosted.port), ("host-model", 6200))
            self.assertEqual(explicit.require_api_key(), "stdin-key")
            self.assertEqual(
                (explicit.gemini_model, explicit.port), ("cli-model", 6300)
            )

    @patch.dict(os.environ, {}, clear=True)
    def test_blank_template_allows_gym_startup_but_requires_a_key_for_planning(self):
        for key in (None, "", " \n ", SecretStr("")):
            with self.subTest(key=key):
                configuration = DirectorSettings(_env_file=None, gemini_api_key=key)
                self.assertEqual(configuration.port, 6090)
                with self.assertRaisesRegex(ValueError, "GEMINI_API_KEY"):
                    configuration.require_api_key()

    @patch.dict(os.environ, {}, clear=True)
    def test_configuration_diagnostics_do_not_expose_credentials_or_invalid_input(self):
        configuration = DirectorSettings(
            _env_file=None, gemini_api_key="private-key-marker"
        )
        self.assertNotIn("private-key-marker", repr(configuration))
        self.assertNotIn("private-key-marker", configuration.model_dump_json())
        with self.assertRaises(ValidationError) as rejected:
            DirectorSettings(
                _env_file=None,
                gemini_api_key="private-key-marker",
                port="invalid-port-marker",
            )
        self.assertNotIn("private-key-marker", str(rejected.exception))
        self.assertNotIn("invalid-port-marker", str(rejected.exception))
