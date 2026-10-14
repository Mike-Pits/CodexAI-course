from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from pro.server import ProApplication


class ProScenarios(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "pro.sqlite3"
        self.env = patch.dict(os.environ, {"MODEL_API_KEY": "", "OPENAI_API_KEY": "", "WORKER_MODEL": ""}, clear=False)
        self.env.start()
        self.app = ProApplication(self.path)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def login(self, username="anna", password="anna-demo"):
        result = self.app.login(username, password)
        self.assertIsNotNone(result)
        token, user = result
        state, fresh_user = self.app.session(token)
        return token, state, fresh_user

    def test_01_short_term_memory_uses_current_dialog(self):
        _, state, anna = self.login()
        self.app.new_dialog(state, anna)
        self.app.chat(state, anna, "Хочу разобраться с функциями")
        result = self.app.chat(state, self.app.db.get_user("anna"), "Продолжи рекомендацию")
        self.assertIn("ранее вы написали", result["message"])
        self.assertIn("разобраться с функциями", result["message"])
        self.assertEqual(len(result["history"]), 4)

    def test_02_long_term_memory_survives_new_dialog_and_restart(self):
        _, state, anna = self.login()
        first = self.app.new_dialog(state, anna)
        self.app.chat(state, anna, "Моя цель — научиться анализировать продажи")
        second = self.app.new_dialog(state, self.app.db.get_user("anna"))
        self.assertNotEqual(first["id"], second["id"])
        reply = self.app.chat(state, self.app.db.get_user("anna"), "Что ты помнишь обо мне?")
        self.assertIn("анализировать продажи", reply["message"])

        restarted = ProApplication(self.path)
        _, new_state, reloaded = self._login_on(restarted, "anna", "anna-demo")
        restarted.new_dialog(new_state, reloaded)
        after_restart = restarted.chat(new_state, reloaded, "Что ты помнишь обо мне?")
        self.assertIn("анализировать продажи", after_restart["message"])

    def _login_on(self, application, username, password):
        result = application.login(username, password)
        self.assertIsNotNone(result)
        token, _ = result
        state, user = application.session(token)
        return token, state, user

    def test_03_database_change_affects_later_answer(self):
        _, anna_state, anna = self.login()
        self.app.new_dialog(anna_state, anna)
        before = self.app.chat(anna_state, anna, "Что мне подойдёт?")["message"]
        self.assertIn("«Самостоятельный»", before)

        _, _, admin = self.login("admin", "admin-demo")
        self.app.update_memory(admin, "anna", {"format": "с наставником", "budget": "до 25 000 ₽"})

        self.app.new_dialog(anna_state, self.app.db.get_user("anna"))
        after = self.app.chat(anna_state, self.app.db.get_user("anna"), "Что мне подойдёт?")["message"]
        self.assertIn("«С наставником»", after)
        self.assertNotEqual(before, after)

    def test_04_client_cannot_read_or_change_another_users_data(self):
        _, anna_state, anna = self.login()
        _, boris_state, boris = self.login("boris", "boris-demo")
        boris_dialog = self.app.new_dialog(boris_state, boris)
        self.app.chat(boris_state, boris, "Хочу изучить веб-разработку")

        with self.assertRaises(PermissionError):
            self.app.list_users(anna)
        with self.assertRaises(PermissionError):
            self.app.update_memory(anna, "boris", {"goal": "чужое значение"})
        with self.assertRaises(PermissionError):
            self.app.delete_memory(anna, "boris", "goal")
        with self.assertRaises(PermissionError):
            self.app.select_dialog(anna_state, anna, boris_dialog["id"])
        self.assertNotEqual(self.app.db.get_user("boris")["profile"]["goal"], "чужое значение")

    def test_memory_can_be_viewed_changed_and_deleted(self):
        _, _, anna = self.login()
        changed = self.app.update_memory(anna, "anna", {"pace": "3 часа в неделю"})
        self.assertEqual(changed["profile"]["pace"], "3 часа в неделю")
        deleted = self.app.delete_memory(anna, "anna", "pace")
        self.assertNotIn("pace", deleted["profile"])

    def test_sql_schema_has_foreign_keys_and_persisted_messages(self):
        _, state, anna = self.login()
        dialog = self.app.new_dialog(state, anna)
        self.app.chat(state, anna, "Сколько стоит курс?")
        counts = self.app.db.counts()
        self.assertEqual(counts["users"], 3)
        self.assertEqual(counts["dialogs"], 1)
        self.assertEqual(counts["messages"], 2)
        with closing(sqlite3.connect(self.path)) as connection:
            foreign_keys = connection.execute("PRAGMA foreign_key_list(messages)").fetchall()
            self.assertTrue(any(row[2] == "dialogs" for row in foreign_keys))
            stored = connection.execute("SELECT COUNT(*) FROM messages WHERE dialog_id = ?", (dialog["id"],)).fetchone()[0]
            self.assertEqual(stored, 2)


if __name__ == "__main__":
    unittest.main()
