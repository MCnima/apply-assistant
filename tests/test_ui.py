import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout

from apply_assistant.data import Database
from apply_assistant.ui import MainWindow, PasteImportDialog


class PasteImportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "paste-test.sqlite3")

    def tearDown(self):
        self.database.close()
        self.temp_dir.cleanup()

    def test_paste_import_requires_valid_preview_then_applies(self):
        dialog = PasteImportDialog(self.database)
        dialog.editor.setPlainText(json.dumps({
            "schema_version": "2.0",
            "universities": [{"id": "university:north", "name": "North University"}],
        }))
        self.assertFalse(dialog.apply_button.isEnabled())
        dialog.preview_import()
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertIn("1 new", dialog.summary.text())
        dialog.apply_import()
        self.assertEqual(self.database.count("universities"), 1)
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertEqual(dialog.import_result["universities"]["added"], 1)

    def test_invalid_pasted_json_does_not_enable_import(self):
        dialog = PasteImportDialog(self.database)
        dialog.editor.setPlainText("{broken")
        dialog.preview_import()
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertIn("validation failed", dialog.summary.text().lower())
        self.assertEqual(self.database.count("universities"), 0)

    def test_editing_pasted_json_invalidates_prior_preview(self):
        dialog = PasteImportDialog(self.database)
        dialog.editor.setPlainText(json.dumps({"schema_version": "2.0"}))
        dialog.preview_import()
        self.assertTrue(dialog.apply_button.isEnabled())
        dialog.editor.appendPlainText(" ")
        self.assertFalse(dialog.apply_button.isEnabled())


class ExternalLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_http_links_are_launchable_and_unsafe_schemes_are_rejected(self):
        self.assertEqual(
            MainWindow.normalized_web_url("www.example.edu/lab"),
            "https://www.example.edu/lab",
        )
        self.assertIsNone(MainWindow.normalized_web_url("javascript:alert(1)"))
        self.assertIsNone(MainWindow.normalized_web_url("https://user:pass@example.edu"))
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "links.sqlite3")
            try:
                window = MainWindow(database)
                layout = QVBoxLayout()
                window.add_line(layout, "Source", "www.example.edu/lab", link=True)
                link_label = layout.itemAt(0).layout().itemAt(1).widget()
                self.assertIsInstance(link_label, QLabel)
                self.assertTrue(link_label.openExternalLinks())
                self.assertIn('href="https://www.example.edu/lab"', link_label.text())
                window.close()
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
