from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agent import local_reply
from app.server import Application


class LiteScenarios(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "store.json"
        self.env = patch.dict(os.environ, {"MODEL_API_KEY": "", "OPENAI_API_KEY": "", "WORKER_MODEL": ""}, clear=False)
        self.env.start()
        self.app = Application(self.path)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def login(self, username: str, password: str):
        result = self.app.login(username, password)
        self.assertIsNotNone(result)
        token, user = result
        state, _ = self.app.session(token)
        return token, state, user

    def test_01_short_term_memory_uses_previous_message(self):
        _, state, user = self.login("anna", "anna-demo")
        first = self.app.chat(state, user, "Хочу понять основы циклов")
        second = self.app.chat(state, user, "А можешь продолжить рекомендацию?")
        self.assertEqual(len(first["history"]), 2)
        self.assertIn("ранее вы написали", second["message"])
        self.assertIn("основы циклов", second["message"])

    def test_02_long_term_memory_survives_new_application(self):
        _, state, user = self.login("anna", "anna-demo")
        result = self.app.chat(state, user, "Меня зовут Алёна, хочу научиться делать Telegram-ботов")
        self.assertEqual(result["saved"]["name"], "Алёна")
        self.assertIn("Telegram-ботов", result["saved"]["goal"])

        restarted = Application(self.path)
        login = restarted.login("anna", "anna-demo")
        self.assertIsNotNone(login)
        _, reloaded_user = login
        self.assertEqual(reloaded_user["profile"]["name"], "Алёна")
        self.assertIn("Telegram-ботов", reloaded_user["profile"]["goal"])

    def test_03_two_clients_receive_their_own_personalization(self):
        anna = self.app.store.get_user("anna")
        boris = self.app.store.get_user("boris")
        anna_reply = local_reply(anna["profile"], [{"role": "user", "content": "Что мне подойдёт?"}])
        boris_reply = local_reply(boris["profile"], [{"role": "user", "content": "Что мне подойдёт?"}])
        self.assertIn("автоматизировать еженедельные отчёты", anna_reply)
        self.assertIn("перейти в Python-разработку", boris_reply)
        self.assertIn("«Самостоятельный»", anna_reply)
        self.assertIn("«С наставником»", boris_reply)

    def test_04_client_cannot_use_admin_operations(self):
        _, _, anna = self.login("anna", "anna-demo")
        with self.assertRaises(PermissionError):
            self.app.list_users(anna)
        with self.assertRaises(PermissionError):
            self.app.update_profile(anna, "boris", {"goal": "взломано"})
        self.assertNotEqual(self.app.store.get_user("boris")["profile"]["goal"], "взломано")

        _, _, admin = self.login("admin", "admin-demo")
        self.assertGreaterEqual(len(self.app.list_users(admin)), 3)

    def test_password_hashes_are_stored_instead_of_plaintext(self):
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn("anna-demo", raw)
        self.assertIn("password_hash", raw)

    def test_store_rejects_unknown_profile_fields(self):
        with self.assertRaises(ValueError):
            self.app.store.update_profile("anna", {"role": "admin"})


if __name__ == "__main__":
    unittest.main()

