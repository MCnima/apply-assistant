import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from apply_assistant.data import Database
from apply_assistant.ui import (
    ApplicationDialog,
    ExternalLinkLabel,
    MainWindow,
    PasteImportDialog,
    PromptDialog,
    ResearcherPromptDialog,
)


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

    def test_profile_json_updates_one_researcher_and_adds_their_records(self):
        self.database.import_json(json.dumps({
            "schema_version": "2.0",
            "universities": [{"id": "university:north", "name": "North University"}],
            "researchers": [{
                "id": "researcher:lee",
                "university_id": "university:north",
                "full_name": "Dr. Lee",
            }],
        }))
        dialog = PasteImportDialog(self.database)
        dialog.editor.setPlainText(json.dumps({
            "schema_version": "2.0",
            "researchers": [{
                "id": "researcher:lee",
                "university_id": "university:north",
                "full_name": "Dr. Lee",
                "research_interests": "Cell signaling and molecular biology.",
                "source_url": "https://north.example.edu/lee",
                "verified_on": "2026-11-11",
                "information_status": "source-confirmed",
            }],
            "opportunities": [{
                "id": "opportunity:researcher:lee:studentship",
                "researcher_id": "researcher:lee",
                "title": "Cell signaling studentship",
                "source_url": "https://north.example.edu/lee/studentship",
                "verified_on": "2026-11-11",
                "information_status": "source-confirmed",
            }],
            "publications": [{
                "id": "publication:researcher:lee:paper-2026",
                "researcher_id": "researcher:lee",
                "title": "Research on cell signaling",
                "source_url": "https://publisher.example/paper",
                "verified_on": "2026-11-11",
                "information_status": "source-confirmed",
            }],
        }))
        dialog.preview_import()
        self.assertTrue(dialog.apply_button.isEnabled())
        dialog.apply_import()
        self.assertEqual(
            self.database.get("researchers", "researcher:lee")["research_interests"],
            "Cell signaling and molecular biology.",
        )
        self.assertEqual(self.database.count("opportunities"), 1)
        self.assertEqual(self.database.count("publications"), 1)


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
                self.assertIsInstance(link_label, ExternalLinkLabel)
                self.assertFalse(link_label.openExternalLinks())
                self.assertIn("Ctrl+click", link_label.toolTip())
                link_label.show()
                with patch("apply_assistant.ui.QDesktopServices.openUrl", return_value=True) as open_url:
                    QTest.mouseClick(
                        link_label, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.ControlModifier,
                    )
                    open_url.assert_called_once()
                    self.assertEqual(open_url.call_args.args[0].toString(), "https://www.example.edu/lab")
                    open_url.reset_mock()
                    QTest.mouseClick(link_label, Qt.MouseButton.LeftButton)
                    open_url.assert_not_called()
                window.close()
            finally:
                database.close()


class DialogContrastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_application_form_and_dropdown_use_light_high_contrast_colors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "contrast.sqlite3")
            try:
                window = MainWindow(database)
                dialog = ApplicationDialog(database, parent=window)
                form_body = dialog.findChild(QWidget, "applicationFormBody")
                self.assertIsNotNone(form_body)
                university_label = next(
                    label for label in dialog.findChildren(QLabel)
                    if label.text() == "University *"
                )
                form_body.ensurePolished()
                university_label.ensurePolished()
                popup = dialog.university.view()
                popup.ensurePolished()
                self.assertEqual(
                    form_body.palette().color(QPalette.ColorRole.Window).name(),
                    "#f3f4f6",
                )
                self.assertEqual(
                    university_label.palette().color(QPalette.ColorRole.WindowText).name(),
                    "#111827",
                )
                self.assertEqual(
                    popup.palette().color(QPalette.ColorRole.Base).name(),
                    "#ffffff",
                )
                self.assertEqual(
                    popup.palette().color(QPalette.ColorRole.Text).name(),
                    "#111827",
                )
                self.assertIn("QComboBox QAbstractItemView", window.styleSheet())
                dialog.close()
                window.close()
            finally:
                database.close()


class ResearcherProfilePromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_profile_button_and_prompt_are_person_specific(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "researcher-profile.sqlite3")
            try:
                database.import_json(json.dumps({
                    "schema_version": "2.0",
                    "universities": [{
                        "id": "university:north",
                        "name": "North University",
                    }],
                    "researchers": [{
                        "id": "researcher:lee",
                        "university_id": "university:north",
                        "full_name": "Dr. Lee",
                        "profile_url": "https://north.example.edu/lee",
                    }],
                }))
                window = MainWindow(database)
                window.show_researcher("researcher:lee")
                button = next(
                    item for item in window.findChildren(QPushButton)
                    if item.text() == "Profile this person"
                )
                self.assertEqual(button.objectName(), "profilePerson")
                self.assertIn("QPushButton#profilePerson", window.styleSheet())
                dialog = ResearcherPromptDialog(
                    database.get("researchers", "researcher:lee"), window
                )
                prompt = dialog.output.toPlainText()
                self.assertIn('"id": "researcher:lee"', prompt)
                self.assertIn("Profile this person", dialog.windowTitle())
                self.assertIn("Paste JSON", dialog.findChild(QLabel).text())
                dialog.close()
                window.close()
            finally:
                database.close()


class DailyPromptDialogSizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_stage_two_prompt_uses_compact_scrollable_layout(self):
        dialog = PromptDialog()
        dialog.stage.setCurrentIndex(1)
        self.assertEqual(dialog.stage.currentData(), "enrichment")
        self.assertFalse(dialog.names_row.isHidden())
        self.assertLessEqual(dialog.width(), 700)
        self.assertLessEqual(dialog.height(), 620)
        self.assertGreaterEqual(dialog.minimumHeight(), 460)
        self.assertEqual(dialog.output.minimumHeight(), 185)
        scroll_areas = dialog.findChildren(QScrollArea)
        self.assertEqual(len(scroll_areas), 1)
        self.assertEqual(scroll_areas[0].maximumHeight(), 240)
        dialog.close()


if __name__ == "__main__":
    unittest.main()
