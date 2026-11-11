"""PySide6 desktop interface for Apply Assistant."""

from __future__ import annotations

import html
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .data import (
    APPLICATION_STATUSES,
    OUTCOMES,
    Database,
    ImportValidationError,
    build_discovery_prompt,
    build_enrichment_prompt,
)


COLORS = {
    "ink": "#17352f",
    "muted": "#667b74",
    "green": "#20765b",
    "green_dark": "#185d49",
    "pale": "#eef6f1",
    "line": "#e1e9e4",
    "canvas": "#f6f8f6",
    "white": "#ffffff",
    "amber": "#fff3d8",
}

APP_STYLE = f"""
QWidget {{ color: {COLORS['ink']}; font-family: "Segoe UI", "Arial"; font-size: 10pt; }}
QMainWindow, QDialog {{ background: {COLORS['canvas']}; }}
QLabel#muted {{ color: {COLORS['muted']}; }}
QLabel#pageTitle {{ font-size: 23pt; font-weight: 650; color: {COLORS['ink']}; }}
QLabel#sectionTitle {{ font-size: 12pt; font-weight: 650; }}
QLabel#brand {{ font-size: 16pt; font-weight: 700; }}
QFrame#card, QFrame#navCard, QFrame#metric {{ background: {COLORS['white']}; border: 1px solid {COLORS['line']}; border-radius: 12px; }}
QFrame#navCard {{ border: none; }}
QFrame#metric {{ padding: 8px; }}
QTreeWidget {{ background: transparent; border: 0; outline: 0; padding: 6px; }}
QTreeWidget::item {{ min-height: 34px; padding: 4px 5px; border-radius: 6px; }}
QTreeWidget::item:selected {{ background: {COLORS['pale']}; color: {COLORS['green_dark']}; }}
QLineEdit, QComboBox, QPlainTextEdit {{ background: {COLORS['white']}; border: 1px solid {COLORS['line']}; border-radius: 8px; padding: 8px 10px; selection-background-color: {COLORS['green']}; }}
QPlainTextEdit {{ line-height: 1.4; }}
QPushButton {{ background: {COLORS['white']}; border: 1px solid {COLORS['line']}; border-radius: 8px; padding: 9px 13px; font-weight: 600; }}
QPushButton:hover {{ background: {COLORS['pale']}; border-color: #b7d5c6; }}
QPushButton#primary {{ background: {COLORS['green']}; color: white; border: 0; }}
QPushButton#primary:hover {{ background: {COLORS['green_dark']}; }}
QPushButton#quiet {{ border: 0; background: transparent; color: {COLORS['green']}; }}
QScrollArea {{ background: transparent; border: 0; }}
"""

STATUS_LABELS = {
    "source-confirmed": "Source checked",
    "user-provided": "User-provided",
    "unknown": "Unverified",
    "suggestion": "Suggested match",
    "sample": "Sample data",
}


class LogoMark(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(38, 38)

    def paintEvent(self, event: Any) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS["green"]))
        painter.drawRoundedRect(1, 1, 36, 36, 11, 11)
        painter.setPen(QPen(QColor("#ffffff"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(18, 28, 18, 12)
        painter.drawLine(18, 18, 11, 13)
        painter.drawLine(18, 21, 25, 14)
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(8, 10, 7, 6)
        painter.drawEllipse(21, 11, 7, 6)
        painter.drawEllipse(15, 6, 7, 7)
        painter.end()


class AddUniversityDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Add a university")
        self.name = QLineEdit()
        self.country = QLineEdit()
        self.website = QLineEdit()
        self.source_url = QLineEdit()
        self.verified_on = QLineEdit()
        self.status = QComboBox()
        self.status.addItems(["user-provided", "source-confirmed", "unknown"])
        form = QFormLayout()
        form.addRow("University name *", self.name)
        form.addRow("Country", self.country)
        form.addRow("Official website", self.website)
        form.addRow("Source URL", self.source_url)
        form.addRow("Verified on", self.verified_on)
        form.addRow("Information status", self.status)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Keep your shortlist organized by institution."))
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setMinimumWidth(420)

    def values(self) -> dict[str, str]:
        return {
            "name": self.name.text(),
            "country": self.country.text(),
            "website": self.website.text(),
            "source_url": self.source_url.text(),
            "verified_on": self.verified_on.text(),
            "information_status": self.status.currentText(),
        }


class AddResearcherDialog(QDialog):
    def __init__(
        self, university_name: str, parent: QWidget | None = None,
        record: dict[str, Any] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Edit researcher profile" if record else "Add a researcher")
        self.record = record or {}
        self.full_name = QLineEdit(self.record.get("full_name", ""))
        self.title = QLineEdit(self.record.get("title", ""))
        self.profile_url = QLineEdit(self.record.get("profile_url", ""))
        self.interests = QPlainTextEdit(self.record.get("research_interests", ""))
        self.interests.setMaximumHeight(90)
        self.email = QLineEdit(self.record.get("email", ""))
        self.notes = QPlainTextEdit(self.record.get("notes", ""))
        self.notes.setMaximumHeight(70)
        self.source_url = QLineEdit(self.record.get("source_url", ""))
        self.verified_on = QLineEdit(self.record.get("verified_on", ""))
        self.information_status = QComboBox()
        self.information_status.addItems(["user-provided", "source-confirmed", "unknown", "suggestion", "sample"])
        self.information_status.setCurrentText(self.record.get("information_status", "user-provided"))
        self.age = QLineEdit(self.record.get("age", ""))
        self.favorite_things = QLineEdit(self.record.get("favorite_things", ""))
        self.linkedin_url = QLineEdit(self.record.get("linkedin_url", ""))
        self.google_scholar_url = QLineEdit(self.record.get("google_scholar_url", ""))
        self.orcid_url = QLineEdit(self.record.get("orcid_url", ""))
        self.other_social_links = QPlainTextEdit(self.record.get("other_social_links", ""))
        self.other_social_links.setMaximumHeight(70)
        self.personal_source_url = QLineEdit(self.record.get("personal_info_source_url", ""))
        self.personal_verified_on = QLineEdit(self.record.get("personal_info_verified_on", ""))
        self.personal_status = QComboBox()
        self.personal_status.addItems(["unknown", "user-provided", "source-confirmed"])
        self.personal_status.setCurrentText(self.record.get("personal_info_status", "unknown"))
        form = QFormLayout()
        form.addRow("University", QLabel(university_name))
        form.addRow("Researcher name *", self.full_name)
        form.addRow("Role / title", self.title)
        form.addRow("Profile URL", self.profile_url)
        form.addRow("Research interests", self.interests)
        form.addRow("Email (publicly listed)", self.email)
        form.addRow("Source URL", self.source_url)
        form.addRow("Verified on", self.verified_on)
        form.addRow("Information status", self.information_status)
        form.addRow("Profile notes", self.notes)
        form.addRow(QLabel("Optional personal details (public self-disclosure only)"))
        form.addRow("Age", self.age)
        form.addRow("Favorite things", self.favorite_things)
        form.addRow("Personal-details source", self.personal_source_url)
        form.addRow("Personal details verified", self.personal_verified_on)
        form.addRow("Personal details status", self.personal_status)
        form.addRow(QLabel("Public profiles and social links"))
        form.addRow("LinkedIn URL", self.linkedin_url)
        form.addRow("Google Scholar URL", self.google_scholar_url)
        form.addRow("ORCID URL", self.orcid_url)
        form.addRow("Other social links (one per line)", self.other_social_links)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "This profile will be nested under the selected university. Only record age or "
            "favorites the person has publicly self-disclosed."
        ))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_body = QWidget()
        form_layout = QVBoxLayout(form_body)
        form_layout.addLayout(form)
        scroll.setWidget(form_body)
        scroll.setMaximumHeight(510)
        layout.addWidget(scroll, 1)
        layout.addWidget(buttons)
        self.setMinimumSize(520, 620)

    def values(self) -> dict[str, str]:
        return {
            "full_name": self.full_name.text().strip(),
            "title": self.title.text().strip(),
            "profile_url": self.profile_url.text().strip(),
            "research_interests": self.interests.toPlainText().strip(),
            "email": self.email.text().strip(),
            "notes": self.notes.toPlainText().strip(),
            "source_url": self.source_url.text().strip(),
            "verified_on": self.verified_on.text().strip(),
            "information_status": self.information_status.currentText(),
            "age": self.age.text().strip(),
            "favorite_things": self.favorite_things.text().strip(),
            "personal_info_source_url": self.personal_source_url.text().strip(),
            "personal_info_verified_on": self.personal_verified_on.text().strip(),
            "personal_info_status": self.personal_status.currentText(),
            "linkedin_url": self.linkedin_url.text().strip(),
            "google_scholar_url": self.google_scholar_url.text().strip(),
            "orcid_url": self.orcid_url.text().strip(),
            "other_social_links": self.other_social_links.toPlainText().strip(),
        }


class PromptDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Daily research prompt")
        self.resize(790, 760)
        self.discipline = QLineEdit()
        self.topic = QLineEdit()
        self.geography = QLineEdit()
        self.university_scope = QLineEdit()
        self.methods = QLineEdit()
        self.date_range = QLineEdit(f"{date.today().isoformat()} to [end date]")
        self.stage = QComboBox()
        self.stage.addItem("Stage 1 · Discover researcher names", "discovery")
        self.stage.addItem("Stage 2 · Enrich selected names", "enrichment")
        self.selected_names = QPlainTextEdit()
        self.selected_names.setPlaceholderText("Paste the names and source notes you selected from Stage 1")
        self.selected_names.setMaximumHeight(100)
        form = QFormLayout()
        form.addRow("Prompt stage", self.stage)
        for label, field in (
            ("Discipline", self.discipline),
            ("Topic / interests", self.topic),
            ("Country / region", self.geography),
            ("University scope", self.university_scope),
            ("Methods / resources", self.methods),
            ("Research window", self.date_range),
        ):
            form.addRow(label, field)
        self.names_row = self.selected_names
        form.addRow("Stage 1 names / notes", self.names_row)
        self.names_row.setVisible(False)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(365)
        self.refresh()
        copy_button = QPushButton("Copy prompt")
        copy_button.setObjectName("primary")
        copy_button.clicked.connect(self.copy_prompt)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        buttons.addWidget(copy_button)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Stage 1 discovers names; select researchers, then use Stage 2 to request sourced "
            "profiles, programs, and publications. Import the verified JSON response. The app "
            "never contacts an AI service. Private application outcomes are excluded from AI updates."
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self.output, 1)
        layout.addLayout(buttons)
        for field in (self.discipline, self.topic, self.geography, self.university_scope,
                      self.methods, self.date_range):
            field.textChanged.connect(self.refresh)
        self.stage.currentIndexChanged.connect(self.on_stage_changed)
        self.selected_names.textChanged.connect(self.refresh)

    def on_stage_changed(self) -> None:
        self.names_row.setVisible(self.stage.currentData() == "enrichment")
        self.refresh()

    def refresh(self) -> None:
        scope = (
            self.discipline.text(), self.topic.text(), self.geography.text(),
            self.university_scope.text(), self.methods.text(), self.date_range.text(),
        )
        if self.stage.currentData() == "enrichment":
            prompt = build_enrichment_prompt(*scope, self.selected_names.toPlainText())
        else:
            prompt = build_discovery_prompt(*scope)
        self.output.setPlainText(prompt)

    def copy_prompt(self) -> None:
        QApplication.clipboard().setText(self.output.toPlainText())
        QMessageBox.information(self, "Prompt copied", "The prompt is ready to paste into your AI chat.")


class RelatedRecordDialog(QDialog):
    def __init__(
        self, record_type: str, researchers: list[dict[str, Any]],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.record_type = record_type
        self.setWindowTitle("Add research program" if record_type == "opportunities" else "Add publication")
        self.title = QLineEdit()
        self.researcher = QComboBox()
        for researcher in researchers:
            self.researcher.addItem(researcher["full_name"], researcher["id"])
        self.deadline = QLineEdit()
        self.year = QLineEdit()
        self.url = QLineEdit()
        self.details = QPlainTextEdit()
        self.details.setMaximumHeight(90)
        self.source_url = QLineEdit()
        self.verified_on = QLineEdit()
        self.status = QComboBox()
        self.status.addItems(["user-provided", "source-confirmed", "unknown", "suggestion", "sample"])
        form = QFormLayout()
        form.addRow("Program title *" if record_type == "opportunities" else "Publication title *", self.title)
        form.addRow("Researcher", self.researcher)
        if record_type == "opportunities":
            form.addRow("Deadline", self.deadline)
            form.addRow("Program details", self.details)
        else:
            form.addRow("Year", self.year)
            form.addRow("Summary", self.details)
        form.addRow("Program / publication URL", self.url)
        form.addRow("Source URL", self.source_url)
        form.addRow("Verified on", self.verified_on)
        form.addRow("Information status", self.status)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setMinimumWidth(500)

    def values(self) -> tuple[str, str, dict[str, str]]:
        researcher_id = self.researcher.currentData()
        details = {
            "url": self.url.text().strip(),
            "source_url": self.source_url.text().strip(),
            "verified_on": self.verified_on.text().strip(),
            "information_status": self.status.currentText(),
        }
        if self.record_type == "opportunities":
            details["deadline"] = self.deadline.text().strip()
            details["details"] = self.details.toPlainText().strip()
        else:
            details["year"] = self.year.text().strip()
            details["summary"] = self.details.toPlainText().strip()
        return self.title.text().strip(), str(researcher_id or ""), details


class ApplicationDialog(QDialog):
    def __init__(
        self, database: Database, record: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.database = database
        self.record = record or {}
        self.setWindowTitle("Update application" if record else "Track an application")
        self.university = QComboBox()
        self.university.addItem("Select a university", "")
        for university in database.rows("universities"):
            self.university.addItem(university["name"], university["id"])
        self.researcher = QComboBox()
        self.researcher.addItem("Not linked", "")
        for person in database.rows("researchers"):
            self.researcher.addItem(person["full_name"], person["id"])
        self.program = QComboBox()
        self.program.addItem("Not linked", "")
        for item in database.rows("opportunities"):
            self.program.addItem(item["title"], item["id"])
        self.title = QLineEdit(self.record.get("title", ""))
        self.status = QComboBox()
        self.status.addItems(APPLICATION_STATUSES)
        self.deadline = QLineEdit(self.record.get("deadline", ""))
        self.next_task = QLineEdit(self.record.get("next_task", ""))
        self.next_task_date = QLineEdit(self.record.get("next_task_date", ""))
        self.outcome = QComboBox()
        self.outcome.addItems(list(OUTCOMES))
        self.outcome_notes = QPlainTextEdit(self.record.get("outcome_notes", ""))
        self.outcome_notes.setMaximumHeight(80)
        self.notes = QPlainTextEdit(self.record.get("notes", ""))
        self.notes.setMaximumHeight(90)
        self.source_url = QLineEdit(self.record.get("source_url", ""))
        self.verified_on = QLineEdit(self.record.get("verified_on", ""))
        for combo, field in (
            (self.university, "university_id"),
            (self.researcher, "researcher_id"),
            (self.program, "program_id"),
            (self.status, "status"),
            (self.outcome, "outcome"),
        ):
            value = self.record.get(field, "researching" if field == "status" else "")
            index = combo.findData(value)
            if index < 0:
                index = combo.findText(value)
            if index >= 0:
                combo.setCurrentIndex(index)
        form = QFormLayout()
        form.addRow("University *", self.university)
        form.addRow("Researcher", self.researcher)
        form.addRow("Program", self.program)
        form.addRow("Application / program *", self.title)
        form.addRow("Stage", self.status)
        form.addRow("Deadline", self.deadline)
        form.addRow("Next task", self.next_task)
        form.addRow("Task date", self.next_task_date)
        form.addRow("Outcome (private)", self.outcome)
        form.addRow("Private outcome notes", self.outcome_notes)
        form.addRow("Private notes", self.notes)
        form.addRow("Source URL", self.source_url)
        form.addRow("Verified on", self.verified_on)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Application stages, outcomes, and notes are stored locally. They are excluded "
            "from research prompts and are never published by the app."
        ))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_body = QWidget()
        form_layout = QVBoxLayout(form_body)
        form_layout.addLayout(form)
        scroll.setWidget(form_body)
        scroll.setMaximumHeight(480)
        layout.addWidget(scroll, 1)
        layout.addWidget(buttons)
        self.setMinimumSize(560, 650)

    def values(self) -> dict[str, str]:
        return {
            "university_id": str(self.university.currentData() or ""),
            "researcher_id": str(self.researcher.currentData() or ""),
            "program_id": str(self.program.currentData() or ""),
            "title": self.title.text().strip(),
            "status": self.status.currentText(),
            "deadline": self.deadline.text().strip(),
            "next_task": self.next_task.text().strip(),
            "next_task_date": self.next_task_date.text().strip(),
            "outcome": self.outcome.currentText(),
            "outcome_notes": self.outcome_notes.toPlainText().strip(),
            "notes": self.notes.toPlainText().strip(),
            "source_url": self.source_url.text().strip(),
            "verified_on": self.verified_on.text().strip(),
            "information_status": "user-provided",
        }


class PasteImportDialog(QDialog):
    def __init__(self, database: Database, parent: QWidget | None = None):
        super().__init__(parent)
        self.database = database
        self._preview_text: str | None = None
        self._preview_counts: dict[str, dict[str, int]] | None = None
        self.import_result: dict[str, dict[str, int]] | None = None
        self.setWindowTitle("Paste JSON import")
        self.resize(820, 720)

        intro = QLabel(
            "Paste a schema 2.0 AI response or a compatible 1.0 export. Validate and review "
            "the counts before applying. Existing records are only updated when stable IDs match."
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            '{\n  "schema_version": "2.0",\n  "universities": [],\n'
            '  "researchers": [],\n  "opportunities": [],\n'
            '  "publications": [],\n  "applications": []\n}'
        )
        self.summary = QLabel("Paste JSON, then select “Validate & preview”.")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)

        self.preview_button = QPushButton("Validate & preview")
        self.preview_button.clicked.connect(self.preview_import)
        self.apply_button = QPushButton("Apply import")
        self.apply_button.setObjectName("primary")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_import)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)

        actions = QHBoxLayout()
        actions.addWidget(self.preview_button)
        actions.addStretch(1)
        actions.addWidget(cancel_button)
        actions.addWidget(self.apply_button)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.summary)
        layout.addLayout(actions)
        self.editor.textChanged.connect(self.invalidate_preview)

    def invalidate_preview(self) -> None:
        self._preview_text = None
        self._preview_counts = None
        self.apply_button.setEnabled(False)
        self.summary.setText("JSON changed. Validate and review the updated import before applying.")

    def preview_import(self) -> None:
        try:
            preview = self.database.preview_import(self.editor.toPlainText())
        except (ImportValidationError, sqlite3.Error) as exc:
            self._preview_text = None
            self._preview_counts = None
            self.apply_button.setEnabled(False)
            self.summary.setText(f"Import validation failed: {exc}")
            return
        self._preview_text = self.editor.toPlainText()
        self._preview_counts = preview["counts"]
        lines = [
            f"{table.title()}: {counts['added']} new, {counts['updated']} matching-ID updates"
            for table, counts in preview["counts"].items()
            if counts["added"] or counts["updated"]
        ]
        if not lines:
            lines.append("No additions or updates.")
        self.summary.setText(
            "Preview ready — omitted records will remain unchanged.\n" + "\n".join(lines)
        )
        self.apply_button.setEnabled(True)

    def apply_import(self) -> None:
        text = self.editor.toPlainText()
        if self._preview_text != text:
            self.invalidate_preview()
            return
        try:
            current_preview = self.database.preview_import(text)
            if current_preview["counts"] != self._preview_counts:
                self._preview_counts = current_preview["counts"]
                self._preview_text = text
                self.preview_import()
                self.summary.setText(
                    "The database changed since your preview. Review the refreshed counts "
                    "before applying.\n" + self.summary.text()
                )
                return
            result = self.database.import_json(text)
        except (ImportValidationError, sqlite3.Error) as exc:
            self._preview_text = None
            self._preview_counts = None
            self.apply_button.setEnabled(False)
            self.summary.setText(f"Import was not applied: {exc}")
            return
        lines = [
            f"{table.title()}: {counts['added']} added, {counts['updated']} updated"
            for table, counts in result.items()
            if counts["added"] or counts["updated"]
        ]
        self.import_result = result
        self.summary.setText("Import complete.\n" + ("\n".join(lines) or "No changes were needed."))
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, database: Database):
        super().__init__()
        self.database = database
        self.setWindowTitle("Apply Assistant")
        self.resize(1250, 800)
        self.setMinimumSize(980, 650)
        self.setStyleSheet(APP_STYLE)
        self._selected_type: str | None = None
        self._selected_id: str | None = None
        self.browse_mode = "tree"
        self._tree_items: dict[tuple[str, str], QTreeWidgetItem] = {}
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(26, 22, 26, 22)
        root_layout.setSpacing(18)

        header = QHBoxLayout()
        identity = QHBoxLayout()
        identity.addWidget(LogoMark())
        brand_stack = QVBoxLayout()
        brand = QLabel("Apply Assistant")
        brand.setObjectName("brand")
        subtitle = QLabel("Your research application workspace")
        subtitle.setObjectName("muted")
        brand_stack.addWidget(brand)
        brand_stack.addWidget(subtitle)
        identity.addLayout(brand_stack)
        header.addLayout(identity)
        header.addStretch(1)
        for title, callback, primary in (
            ("Track application", self.add_application, False),
            ("Daily AI prompt", self.open_prompt, False),
            ("Paste JSON", self.paste_import_data, False),
            ("Import JSON", self.import_data, True),
            ("Export", self.export_data, False),
        ):
            button = QPushButton(title)
            if primary:
                button.setObjectName("primary")
            button.clicked.connect(callback)
            header.addWidget(button)
        root_layout.addLayout(header)

        self.metrics = QHBoxLayout()
        self.metric_labels: dict[str, QLabel] = {}
        for table, heading in (
            ("universities", "Universities"),
            ("researchers", "Researchers"),
            ("opportunities", "Opportunities"),
            ("publications", "Publications"),
            ("applications", "Applications"),
        ):
            card = QFrame()
            card.setObjectName("metric")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 10, 14, 10)
            count = QLabel("0")
            count.setStyleSheet("font-size: 18pt; font-weight: 700;")
            caption = QLabel(heading)
            caption.setObjectName("muted")
            card_layout.addWidget(count)
            card_layout.addWidget(caption)
            self.metric_labels[table] = count
            self.metrics.addWidget(card, 1)
        root_layout.addLayout(self.metrics)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        nav_frame = QFrame()
        nav_frame.setObjectName("navCard")
        nav_layout = QVBoxLayout(nav_frame)
        nav_layout.setContentsMargins(14, 14, 14, 14)
        nav_head = QHBoxLayout()
        nav_title = QLabel("Your shortlist")
        nav_title.setObjectName("sectionTitle")
        nav_head.addWidget(nav_title)
        nav_head.addStretch(1)
        add_university = QPushButton("+ University")
        add_university.setObjectName("quiet")
        add_university.clicked.connect(self.add_university)
        nav_head.addWidget(add_university)
        nav_layout.addLayout(nav_head)
        self.browse_selector = QComboBox()
        self.browse_selector.addItem("University tree", "tree")
        for table, label in (
            ("universities", "All universities"),
            ("researchers", "All researchers"),
            ("opportunities", "All research programs"),
            ("publications", "All publications"),
            ("applications", "My applications"),
        ):
            self.browse_selector.addItem(label, table)
        self.browse_selector.currentIndexChanged.connect(self.change_browse_mode)
        nav_layout.addWidget(self.browse_selector)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search universities and researchers")
        self.search.textChanged.connect(self.filter_tree)
        nav_layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemSelectionChanged.connect(self.selection_changed)
        nav_layout.addWidget(self.tree, 1)
        self.add_record_button = QPushButton("+ Add record")
        self.add_record_button.clicked.connect(self.add_current_record_type)
        nav_layout.addWidget(self.add_record_button)
        splitter.addWidget(nav_frame)

        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_body = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_body)
        self.detail_layout.setContentsMargins(22, 12, 12, 16)
        self.detail_layout.setSpacing(16)
        self.detail_scroll.setWidget(self.detail_body)
        splitter.addWidget(self.detail_scroll)
        splitter.setSizes([325, 850])
        root_layout.addWidget(splitter, 1)

        footer = QHBoxLayout()
        footer_message = QLabel(
            f"Version {__version__} · Local data only. Imports add records; only matching IDs update."
        )
        footer_message.setObjectName("muted")
        footer.addWidget(footer_message)
        footer.addStretch(1)
        backup = QPushButton("Back up database")
        backup.clicked.connect(self.backup_data)
        footer.addWidget(backup)
        root_layout.addLayout(footer)
        self.setCentralWidget(root)

    def refresh(self, focus: tuple[str, str] | None = None) -> None:
        if focus and focus[0] not in {"universities", "researchers"} and self.browse_mode == "tree":
            index = self.browse_selector.findData(focus[0])
            if index >= 0:
                self.browse_selector.setCurrentIndex(index)
                return
        self._tree_items.clear()
        self.tree.clear()
        for table, label in (
            ("universities", "Universities"),
            ("researchers", "Researchers"),
            ("opportunities", "Opportunities"),
            ("publications", "Publications"),
            ("applications", "Applications"),
        ):
            self.metric_labels[table].setText(str(self.database.count(table)))
        if self.browse_mode != "tree":
            table = self.browse_mode
            labels = {
                "universities": lambda row: row["name"],
                "researchers": lambda row: row["full_name"],
                "opportunities": lambda row: row["title"],
                "publications": lambda row: row["title"],
                "applications": lambda row: row["title"],
            }
            for record in self.database.rows(table):
                item = QTreeWidgetItem([labels[table](record)])
                item.setData(0, Qt.ItemDataRole.UserRole, table)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, record["id"])
                self.tree.addTopLevelItem(item)
                self._tree_items[(table, record["id"])] = item
        else:
            researchers_by_university: dict[str, list[dict[str, Any]]] = {}
            for researcher in self.database.rows("researchers"):
                researchers_by_university.setdefault(researcher["university_id"], []).append(researcher)

            for university in self.database.rows("universities"):
                university_item = QTreeWidgetItem([university["name"]])
                university_item.setData(0, Qt.ItemDataRole.UserRole, "universities")
                university_item.setData(0, Qt.ItemDataRole.UserRole + 1, university["id"])
                self.tree.addTopLevelItem(university_item)
                self._tree_items[("universities", university["id"])] = university_item
                for researcher in researchers_by_university.get(university["id"], []):
                    item = QTreeWidgetItem([researcher["full_name"]])
                    item.setData(0, Qt.ItemDataRole.UserRole, "researchers")
                    item.setData(0, Qt.ItemDataRole.UserRole + 1, researcher["id"])
                    university_item.addChild(item)
                    self._tree_items[("researchers", researcher["id"])] = item
                university_item.setExpanded(True)

        self.add_record_button.setText(self._add_label())

        self.filter_tree(self.search.text())
        if focus and focus in self._tree_items:
            item = self._tree_items[focus]
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)
        elif self.tree.topLevelItemCount():
            if self._selected_type and self._selected_id:
                old = self._tree_items.get((self._selected_type, self._selected_id))
                if old:
                    self.tree.setCurrentItem(old)
                    return
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        else:
            self._selected_type = None
            self._selected_id = None
            self.show_empty_state()

    def filter_tree(self, query: str) -> None:
        needle = query.casefold().strip()
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            parent_match = needle in parent.text(0).casefold()
            visible_children = 0
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                visible = not needle or parent_match or needle in child.text(0).casefold()
                child.setHidden(not visible)
                visible_children += int(visible)
            parent.setHidden(bool(needle) and not parent_match and visible_children == 0)

    def selection_changed(self) -> None:
        selected = self.tree.selectedItems()
        if not selected:
            return
        item = selected[0]
        self._selected_type = item.data(0, Qt.ItemDataRole.UserRole)
        self._selected_id = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if self._selected_type == "universities":
            self.show_university(self._selected_id)
        elif self._selected_type == "researchers":
            self.show_researcher(self._selected_id)
        elif self._selected_type == "opportunities":
            self.show_opportunity(self._selected_id)
        elif self._selected_type == "publications":
            self.show_publication(self._selected_id)
        elif self._selected_type == "applications":
            self.show_application(self._selected_id)

    def change_browse_mode(self) -> None:
        self.browse_mode = str(self.browse_selector.currentData() or "tree")
        self.refresh()

    def _add_label(self) -> str:
        return {
            "tree": "+ Add researcher",
            "universities": "+ Add university",
            "researchers": "+ Add researcher",
            "opportunities": "+ Add research program",
            "publications": "+ Add publication",
            "applications": "+ Track application",
        }[self.browse_mode]

    def add_current_record_type(self) -> None:
        if self.browse_mode in ("tree", "researchers"):
            self.add_researcher()
        elif self.browse_mode == "universities":
            self.add_university()
        elif self.browse_mode in ("opportunities", "publications"):
            self.add_related_record(self.browse_mode)
        else:
            self.add_application()

    def clear_detail(self) -> None:
        while self.detail_layout.count():
            entry = self.detail_layout.takeAt(0)
            widget = entry.widget()
            if widget:
                widget.deleteLater()

    def add_card(self, heading: str | None = None) -> QVBoxLayout:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 17, 20, 17)
        layout.setSpacing(10)
        if heading:
            title = QLabel(heading)
            title.setObjectName("sectionTitle")
            layout.addWidget(title)
        self.detail_layout.addWidget(card)
        return layout

    def show_empty_state(self) -> None:
        self.clear_detail()
        self._selected_type = None
        self._selected_id = None
        title = QLabel("Start with a university")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Build a shortlist from the top down. Add an institution, then add its researchers, "
            "or use your daily AI prompt and import a structured update."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("muted")
        self.detail_layout.addSpacing(30)
        self.detail_layout.addWidget(title)
        self.detail_layout.addWidget(subtitle)
        actions = QHBoxLayout()
        add = QPushButton("Add your first university")
        add.setObjectName("primary")
        add.clicked.connect(self.add_university)
        import_button = QPushButton("Import AI research JSON")
        import_button.clicked.connect(self.import_data)
        actions.addWidget(add)
        actions.addWidget(import_button)
        actions.addStretch(1)
        self.detail_layout.addLayout(actions)
        self.detail_layout.addStretch(1)

    def show_university(self, university_id: str) -> None:
        university = self.database.get("universities", university_id)
        if not university:
            self.refresh()
            return
        self.clear_detail()
        title = QLabel(university["name"])
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setObjectName("pageTitle")
        self.detail_layout.addWidget(title)
        subtitle = " · ".join(filter(None, [university["country"], "University profile"]))
        subtitle_label = QLabel(subtitle)
        subtitle_label.setTextFormat(Qt.TextFormat.PlainText)
        subtitle_label.setObjectName("muted")
        self.detail_layout.addWidget(subtitle_label)
        self.add_status_badge(university)
        self.add_delete_button("universities", university)
        overview = self.add_card("Institution")
        self.add_line(overview, "Website", university.get("website"), link=True)
        self.add_line(overview, "Notes", university.get("notes"))
        self.add_line(overview, "Source", university.get("source_url"), link=True)
        self.add_line(overview, "Last verified", university.get("verified_on"))
        researchers = [
            item for item in self.database.rows("researchers")
            if item["university_id"] == university_id
        ]
        panel = self.add_card(f"Researchers · {len(researchers)}")
        if not researchers:
            note = QLabel("No researchers added yet. Keep every profile connected to this university.")
            note.setObjectName("muted")
            panel.addWidget(note)
        else:
            for researcher in researchers:
                button = QPushButton(f"{researcher['full_name']}   ›")
                button.setStyleSheet(
                    "text-align: left; padding: 12px; background: #f7faf8; border: 0;"
                )
                button.clicked.connect(
                    lambda checked=False, rid=researcher["id"]: self.select_record("researchers", rid)
                )
                panel.addWidget(button)
        add = QPushButton("+ Add researcher here")
        add.setObjectName("primary")
        add.clicked.connect(self.add_researcher)
        self.detail_layout.addWidget(add, alignment=Qt.AlignmentFlag.AlignLeft)
        self.detail_layout.addStretch(1)

    def show_researcher(self, researcher_id: str) -> None:
        researcher = self.database.get("researchers", researcher_id)
        if not researcher:
            self.refresh()
            return
        university = self.database.get("universities", researcher["university_id"])
        self.clear_detail()
        name = QLabel(researcher["full_name"])
        name.setTextFormat(Qt.TextFormat.PlainText)
        name.setObjectName("pageTitle")
        self.detail_layout.addWidget(name)
        title = QLabel(researcher.get("title") or "Researcher")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setObjectName("muted")
        self.detail_layout.addWidget(title)
        self.add_status_badge(researcher)
        self.add_delete_button("researchers", researcher)
        if university:
            institution = QPushButton(f"‹  {university['name']}")
            institution.setObjectName("quiet")
            institution.clicked.connect(
                lambda checked=False, uid=university["id"]: self.select_record("universities", uid)
            )
            self.detail_layout.addWidget(institution, alignment=Qt.AlignmentFlag.AlignLeft)
        details = self.add_card("Researcher profile")
        self.add_line(details, "Research interests", researcher.get("research_interests"))
        self.add_line(details, "Profile", researcher.get("profile_url"), link=True)
        self.add_line(details, "Email", researcher.get("email"))
        self.add_line(details, "Notes", researcher.get("notes"))
        self.add_line(details, "Source", researcher.get("source_url"), link=True)
        self.add_line(details, "Last verified", researcher.get("verified_on"))
        personal = self.add_card("Public profile & self-disclosed details")
        for label, field in (
            ("Age (only if self-disclosed)", "age"),
            ("Favorite things (only if self-disclosed)", "favorite_things"),
            ("Personal-info status", "personal_info_status"),
            ("Personal-info source", "personal_info_source_url"),
            ("Personal-info verified", "personal_info_verified_on"),
            ("LinkedIn", "linkedin_url"),
            ("Google Scholar", "google_scholar_url"),
            ("ORCID", "orcid_url"),
        ):
            self.add_line(personal, label, researcher.get(field), link=field.endswith("_url"))
        other_links = researcher.get("other_social_links", "").splitlines()
        for index, value in enumerate(other_links, 1):
            self.add_line(personal, f"Other profile {index}", value, link=True)

        edit = QPushButton("Edit researcher profile")
        edit.clicked.connect(lambda checked=False, row=researcher: self.edit_researcher(row))
        self.detail_layout.addWidget(edit, alignment=Qt.AlignmentFlag.AlignLeft)
        opportunities = [
            row for row in self.database.rows("opportunities")
            if row.get("researcher_id") == researcher_id
        ]
        publications = [
            row for row in self.database.rows("publications")
            if row.get("researcher_id") == researcher_id
        ]
        self.add_related_dropdown("Research programs", opportunities, "opportunities")
        self.add_related_dropdown("Publications", publications, "publications")
        applications = [
            row for row in self.database.rows("applications")
            if row.get("researcher_id") == researcher_id
        ]
        self.add_related_dropdown("Applications · private", applications, "applications")
        self.detail_layout.addStretch(1)

    def add_related_dropdown(
        self, heading: str, records: list[dict[str, Any]], record_type: str,
    ) -> None:
        button = QToolButton()
        button.setText(f"{heading} · {len(records)}")
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setArrowType(Qt.ArrowType.DownArrow)
        button.setCheckable(True)
        button.setChecked(True)
        button.setStyleSheet(
            "QToolButton {background:white; border:1px solid "
            + COLORS["line"]
            + "; border-radius:9px; padding:12px; font-size:11pt; font-weight:650;}"
        )
        panel = QFrame()
        panel.setObjectName("card")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(17, 15, 17, 15)
        panel_layout.setSpacing(8)
        if not records:
            empty = QLabel(f"No {heading.lower()} to display yet.")
            empty.setObjectName("muted")
            panel_layout.addWidget(empty)
        for record in records:
            title = QLabel(record["title"])
            title.setTextFormat(Qt.TextFormat.PlainText)
            title.setStyleSheet("font-weight: 650;")
            panel_layout.addWidget(title)
            if record_type == "opportunities":
                self.add_line(panel_layout, "Deadline", record.get("deadline"))
                self.add_line(panel_layout, "Details", record.get("details"))
            elif record_type == "publications":
                self.add_line(panel_layout, "Year", record.get("year"))
                self.add_line(panel_layout, "Summary", record.get("summary"))
            else:
                self.add_line(panel_layout, "Stage", record.get("status"))
                self.add_line(panel_layout, "Deadline", record.get("deadline"))
                self.add_line(panel_layout, "Next task", record.get("next_task"))
                self.add_line(panel_layout, "Task date", record.get("next_task_date"))
                self.add_line(panel_layout, "Outcome", record.get("outcome"))
                self.add_line(panel_layout, "Private outcome notes", record.get("outcome_notes"))
            self.add_line(panel_layout, "Link", record.get("url"), link=True)
            self.add_line(panel_layout, "Source", record.get("source_url"), link=True)
            panel_layout.addWidget(self.status_label(record))
            if record_type == "applications":
                edit = QPushButton("Update status / outcome")
                edit.clicked.connect(
                    lambda checked=False, row=record: self.edit_application(row)
                )
                panel_layout.addWidget(edit, alignment=Qt.AlignmentFlag.AlignLeft)
            self.add_delete_button(record_type, record, panel_layout)
        self.detail_layout.addWidget(button)
        self.detail_layout.addWidget(panel)
        button.toggled.connect(
            lambda checked, content=panel, toggle=button: self.toggle_dropdown(
                checked, content, toggle
            )
        )

    @staticmethod
    def toggle_dropdown(checked: bool, content: QWidget, button: QToolButton) -> None:
        content.setVisible(checked)
        button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

    def show_opportunity(self, record_id: str) -> None:
        record = self.database.get("opportunities", record_id)
        if not record:
            self.refresh()
            return
        self.clear_detail()
        title = QLabel(record["title"])
        title.setObjectName("pageTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_layout.addWidget(title)
        self.add_status_badge(record)
        self.add_delete_button("opportunities", record)
        details = self.add_card("Research program")
        self.add_line(details, "Details", record.get("details"))
        self.add_line(details, "Deadline", record.get("deadline"))
        self.add_line(details, "Program link", record.get("url"), link=True)
        self.add_line(details, "Source", record.get("source_url"), link=True)
        self.add_line(details, "Last verified", record.get("verified_on"))
        researcher = self.database.get("researchers", record.get("researcher_id") or "")
        if researcher:
            link = QPushButton(f"Researcher: {researcher['full_name']}")
            link.setObjectName("quiet")
            link.clicked.connect(
                lambda checked=False, rid=researcher["id"]: self.select_record("researchers", rid)
            )
            self.detail_layout.addWidget(link, alignment=Qt.AlignmentFlag.AlignLeft)
        self.detail_layout.addStretch(1)

    def show_publication(self, record_id: str) -> None:
        record = self.database.get("publications", record_id)
        if not record:
            self.refresh()
            return
        self.clear_detail()
        title = QLabel(record["title"])
        title.setObjectName("pageTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_layout.addWidget(title)
        self.add_status_badge(record)
        self.add_delete_button("publications", record)
        details = self.add_card("Publication")
        self.add_line(details, "Year", record.get("year"))
        self.add_line(details, "Summary", record.get("summary"))
        self.add_line(details, "Publication link", record.get("url"), link=True)
        self.add_line(details, "Source", record.get("source_url"), link=True)
        self.add_line(details, "Last verified", record.get("verified_on"))
        researcher = self.database.get("researchers", record.get("researcher_id") or "")
        if researcher:
            link = QPushButton(f"Researcher: {researcher['full_name']}")
            link.setObjectName("quiet")
            link.clicked.connect(
                lambda checked=False, rid=researcher["id"]: self.select_record("researchers", rid)
            )
            self.detail_layout.addWidget(link, alignment=Qt.AlignmentFlag.AlignLeft)
        self.detail_layout.addStretch(1)

    def show_application(self, record_id: str) -> None:
        record = self.database.get("applications", record_id)
        if not record:
            self.refresh()
            return
        university = self.database.get("universities", record["university_id"])
        self.clear_detail()
        title = QLabel(record["title"])
        title.setObjectName("pageTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_layout.addWidget(title)
        self.add_status_badge(record)
        privacy = QLabel("Private application record · stored locally · not published")
        privacy.setObjectName("muted")
        self.detail_layout.addWidget(privacy)
        if university:
            link = QPushButton(f"University: {university['name']}")
            link.setObjectName("quiet")
            link.clicked.connect(
                lambda checked=False, uid=university["id"]: self.select_record("universities", uid)
            )
            self.detail_layout.addWidget(link, alignment=Qt.AlignmentFlag.AlignLeft)
        details = self.add_card("Application progress")
        for label, field in (
            ("Stage", "status"), ("Deadline", "deadline"),
            ("Next task", "next_task"), ("Task date", "next_task_date"),
            ("Outcome", "outcome"), ("Private outcome notes", "outcome_notes"),
            ("Private notes", "notes"), ("Source", "source_url"),
            ("Verified on", "verified_on"),
        ):
            self.add_line(details, label, record.get(field), link=(field == "source_url"))
        edit = QPushButton("Update status / outcome / task")
        edit.setObjectName("primary")
        edit.clicked.connect(lambda checked=False, row=record: self.edit_application(row))
        self.detail_layout.addWidget(edit, alignment=Qt.AlignmentFlag.AlignLeft)
        self.add_delete_button("applications", record)
        self.detail_layout.addStretch(1)

    def add_status_badge(self, record: dict[str, Any]) -> None:
        badge = self.status_label(record)
        self.detail_layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignLeft)

    def status_label(self, record: dict[str, Any]) -> QLabel:
        status = record.get("information_status", "unknown")
        label = QLabel(STATUS_LABELS.get(status, status))
        label.setStyleSheet(
            "background: #e8f4ec; color: #22624b; padding: 5px 9px; "
            "border-radius: 8px; font-size: 9pt;"
            if status == "source-confirmed"
            else "background: #f1f3f1; color: #596a62; padding: 5px 9px; "
                 "border-radius: 8px; font-size: 9pt;"
        )
        return label

    def add_line(
        self, layout: QVBoxLayout, label: str, value: str | None, link: bool = False,
    ) -> None:
        if not value:
            return
        row = QHBoxLayout()
        key = QLabel(label)
        key.setObjectName("muted")
        key.setMinimumWidth(115)
        value_label = QLabel()
        value_label.setWordWrap(True)
        if link:
            external_url = self.normalized_web_url(value)
            if external_url:
                safe_value = html.escape(external_url, quote=True)
                safe_text = html.escape(value, quote=True)
                value_label.setText(
                    f'<a href="{safe_value}" style="color: {COLORS["green"]}">{safe_text}</a>'
                )
                value_label.setOpenExternalLinks(True)
            else:
                value_label.setTextFormat(Qt.TextFormat.PlainText)
                value_label.setText(value)
        else:
            value_label.setTextFormat(Qt.TextFormat.PlainText)
            value_label.setText(value)
        row.addWidget(key, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(value_label, 1)
        layout.addLayout(row)

    @staticmethod
    def normalized_web_url(value: str) -> str | None:
        candidate = value.strip()
        if not candidate:
            return None
        parsed = QUrl(candidate)
        if not parsed.scheme():
            parsed = QUrl("https://" + candidate)
        if (
            parsed.scheme().lower() not in {"http", "https"}
            or not parsed.host()
            or parsed.userInfo()
        ):
            return None
        return parsed.toString()

    def select_record(self, table: str, record_id: str) -> None:
        if (table, record_id) not in self._tree_items:
            index = self.browse_selector.findData(table)
            if index >= 0:
                self.browse_selector.setCurrentIndex(index)
        item = self._tree_items.get((table, record_id))
        if item:
            self.tree.setCurrentItem(item)

    def add_delete_button(
        self, table: str, record: dict[str, Any],
        layout: QVBoxLayout | None = None,
    ) -> None:
        button = QPushButton("Delete record…")
        button.setStyleSheet(
            "QPushButton {color:#963e37; border-color:#e9c4c0;}"
            "QPushButton:hover {background:#fff0ee;}"
        )
        button.clicked.connect(
            lambda checked=False, record_type=table, record_id=record["id"]:
            self.delete_record(record_type, record_id)
        )
        if layout is None:
            self.detail_layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)
        else:
            layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)

    def delete_record(self, table: str, record_id: str) -> None:
        record = self.database.get(table, record_id)
        if not record:
            self.refresh()
            return
        title_field = {
            "universities": "name", "researchers": "full_name",
            "opportunities": "title", "publications": "title",
            "applications": "title",
        }[table]
        counts = self.database.delete_counts(table, record_id)
        names = {
            "researchers": "researcher(s)", "programs": "program(s)",
            "publications": "publication(s)", "applications": "application record(s)",
        }
        impacted = [
            f"{count} linked {names.get(key, key)}"
            for key, count in counts.items() if count
        ]
        message = f"Delete “{record[title_field]}”?"
        if impacted:
            message += "\n\nThis also permanently deletes:\n• " + "\n• ".join(impacted)
        else:
            message += "\n\nThis action cannot be undone."
        if table == "applications":
            message += "\n\nThis private application record and outcome notes will be deleted."
        if QMessageBox.question(
            self, "Confirm deletion", message,
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.database.delete_record(table, record_id)
            self._selected_type = None
            self._selected_id = None
            self.refresh()
        except sqlite3.Error as exc:
            self.show_error("Could not delete record", exc)

    def _validate_source(self, values: dict[str, str], label: str) -> bool:
        if values.get("information_status") == "source-confirmed":
            if not values.get("source_url") or not values.get("verified_on"):
                QMessageBox.warning(
                    self, "Source details required",
                    f"A source-confirmed {label} needs both a source URL and a verification date.",
                )
                return False
        return True

    def add_university(self) -> None:
        dialog = AddUniversityDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values["name"].strip():
            QMessageBox.warning(self, "Name required", "Enter a university name to continue.")
            return
        if not self._validate_source(values, "university"):
            return
        try:
            name, country, website = values["name"], values["country"], values["website"]
            record_id = self.database.add_university(
                name, country, website,
                source_url=values["source_url"],
                verified_on=values["verified_on"],
                information_status=values["information_status"],
            )
            self.refresh(("universities", record_id))
        except sqlite3.Error as exc:
            self.show_error("Could not add university", exc)

    def add_researcher(self) -> None:
        university_id = self._selected_id if self._selected_type == "universities" else None
        if not university_id and self._selected_type == "researchers":
            selected = self.database.get("researchers", self._selected_id or "")
            university_id = selected["university_id"] if selected else None
        if not university_id:
            QMessageBox.information(
                self, "Select a university", "Select a university in the tree before adding a researcher."
            )
            return
        university = self.database.get("universities", university_id)
        if not university:
            return
        dialog = AddResearcherDialog(university["name"], self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        full_name = values["full_name"]
        if not full_name:
            QMessageBox.warning(self, "Name required", "Enter a researcher name to continue.")
            return
        if not self._validate_source(values, "researcher"):
            return
        has_personal_details = bool(values["age"] or values["favorite_things"])
        if (
            has_personal_details
            and (
                values["personal_info_status"] != "source-confirmed"
                or not values["personal_info_source_url"]
                or not values["personal_info_verified_on"]
            )
        ) or (
            values["personal_info_status"] == "source-confirmed"
            and not has_personal_details
        ):
            QMessageBox.warning(
                self, "Personal source required",
                "Age or favorite things may only be saved when publicly self-disclosed, "
                "source-confirmed, and accompanied by a source URL and verification date.",
            )
            return
        try:
            researcher_id = self.database.add_researcher(
                university_id, full_name,
                values.pop("title"), values.pop("profile_url"),
                values.pop("research_interests"), **values,
            )
            self.refresh(("researchers", researcher_id))
        except sqlite3.Error as exc:
            self.show_error("Could not add researcher", exc)

    def edit_researcher(self, record: dict[str, Any]) -> None:
        university = self.database.get("universities", record["university_id"])
        if not university:
            return
        dialog = AddResearcherDialog(university["name"], self, record)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values["full_name"]:
            QMessageBox.warning(self, "Name required", "Enter a researcher name to continue.")
            return
        if not self._validate_source(values, "researcher"):
            return
        has_personal_details = bool(values["age"] or values["favorite_things"])
        if (
            has_personal_details
            and (
                values["personal_info_status"] != "source-confirmed"
                or not values["personal_info_source_url"]
                or not values["personal_info_verified_on"]
            )
        ) or (
            values["personal_info_status"] == "source-confirmed"
            and not has_personal_details
        ):
            QMessageBox.warning(
                self, "Personal source required",
                "Age or favorite things may only be saved when publicly self-disclosed, "
                "source-confirmed, and accompanied by a source URL and verification date.",
            )
            return
        try:
            self.database.update_record("researchers", record["id"], values)
            self.refresh(("researchers", record["id"]))
        except (sqlite3.Error, ValueError) as exc:
            self.show_error("Could not update researcher", exc)

    def add_related_record(self, table: str) -> None:
        researchers = self.database.rows("researchers")
        if not researchers:
            QMessageBox.information(
                self, "Add a researcher first",
                "Research programs and publications need to be linked to a researcher.",
            )
            return
        dialog = RelatedRecordDialog(table, researchers, self)
        if self._selected_type == "researchers" and self._selected_id:
            index = dialog.researcher.findData(self._selected_id)
            if index >= 0:
                dialog.researcher.setCurrentIndex(index)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        title, researcher_id, details = dialog.values()
        if not title:
            QMessageBox.warning(self, "Title required", "Enter a title to continue.")
            return
        if not self._validate_source(details, "research record"):
            return
        try:
            record_id = (
                self.database.add_opportunity(title, researcher_id or None, **details)
                if table == "opportunities"
                else self.database.add_publication(title, researcher_id, **details)
            )
            self.refresh((table, record_id))
        except sqlite3.Error as exc:
            self.show_error("Could not add record", exc)

    def add_application(self) -> None:
        if not self.database.rows("universities"):
            QMessageBox.information(
                self, "Add a university first",
                "Create a university before tracking an application.",
            )
            return
        dialog = ApplicationDialog(self.database, parent=self)
        if self._selected_type == "universities" and self._selected_id:
            index = dialog.university.findData(self._selected_id)
            if index >= 0:
                dialog.university.setCurrentIndex(index)
        elif self._selected_type == "researchers" and self._selected_id:
            person = self.database.get("researchers", self._selected_id)
            if person:
                index = dialog.university.findData(person["university_id"])
                if index >= 0:
                    dialog.university.setCurrentIndex(index)
                index = dialog.researcher.findData(self._selected_id)
                if index >= 0:
                    dialog.researcher.setCurrentIndex(index)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values["university_id"] or not values["title"]:
            QMessageBox.warning(self, "Required fields", "Select a university and enter an application title.")
            return
        researcher = self.database.get("researchers", values["researcher_id"]) if values["researcher_id"] else None
        program = self.database.get("opportunities", values["program_id"]) if values["program_id"] else None
        if researcher and researcher["university_id"] != values["university_id"]:
            QMessageBox.warning(self, "University mismatch", "The selected researcher belongs to another university.")
            return
        if program and program.get("researcher_id"):
            program_researcher = self.database.get("researchers", program["researcher_id"])
            if program_researcher and program_researcher["university_id"] != values["university_id"]:
                QMessageBox.warning(self, "University mismatch", "The selected program belongs to another university.")
                return
        try:
            record_id = self.database.add_application(
                values.pop("university_id"), values.pop("title"), **values
            )
            self.refresh(("applications", record_id))
        except sqlite3.Error as exc:
            self.show_error("Could not track application", exc)

    def edit_application(self, record: dict[str, Any]) -> None:
        dialog = ApplicationDialog(self.database, record, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values["university_id"] or not values["title"]:
            QMessageBox.warning(self, "Required fields", "Select a university and enter an application title.")
            return
        researcher = self.database.get("researchers", values["researcher_id"]) if values["researcher_id"] else None
        program = self.database.get("opportunities", values["program_id"]) if values["program_id"] else None
        if researcher and researcher["university_id"] != values["university_id"]:
            QMessageBox.warning(self, "University mismatch", "The selected researcher belongs to another university.")
            return
        if program and program.get("researcher_id"):
            program_researcher = self.database.get("researchers", program["researcher_id"])
            if program_researcher and program_researcher["university_id"] != values["university_id"]:
                QMessageBox.warning(self, "University mismatch", "The selected program belongs to another university.")
                return
        try:
            self.database.update_record("applications", record["id"], values)
            self.refresh(("applications", record["id"]))
        except (sqlite3.Error, ValueError) as exc:
            self.show_error("Could not update application", exc)

    def import_data(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import research JSON", str(Path.home()), "JSON files (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
            preview = self.database.preview_import(text)
        except (OSError, UnicodeError, ImportValidationError) as exc:
            self.show_error("Import could not be previewed", exc)
            return
        lines = []
        for table, counts in preview["counts"].items():
            if counts["added"] or counts["updated"]:
                lines.append(
                    f"{table.title()}: {counts['added']} new, {counts['updated']} matching-ID updates"
                )
        if not lines:
            lines.append("No records to add or update.")
        message = (
            "Review the changes before they are applied:\n\n"
            + "\n".join(lines)
            + "\n\nUnmatched existing data will be kept. Only records with matching IDs are updated."
        )
        if QMessageBox.question(
            self, "Import preview", message,
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Ok,
        ) != QMessageBox.StandardButton.Ok:
            return
        try:
            result = self.database.import_json(text)
            summary = "\n".join(
                f"{table.title()}: {values['added']} added, {values['updated']} updated"
                for table, values in result.items()
                if values["added"] or values["updated"]
            ) or "No changes were needed."
            QMessageBox.information(self, "Import complete", summary)
            self.refresh()
        except ImportValidationError as exc:
            self.show_error("Import was not applied", exc)

    def paste_import_data(self) -> None:
        dialog = PasteImportDialog(self.database, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            result = dialog.import_result or {}
            lines = [
                f"{table.title()}: {counts['added']} added, {counts['updated']} updated"
                for table, counts in result.items()
                if counts["added"] or counts["updated"]
            ]
            QMessageBox.information(
                self, "Import complete",
                "\n".join(lines) or "No changes were needed.",
            )

    def export_data(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export database as JSON", str(Path.home() / "apply-assistant-export.json"),
            "JSON files (*.json)",
        )
        if not path:
            return
        try:
            Path(path).write_text(self.database.export_json(), encoding="utf-8")
            QMessageBox.information(self, "Export complete", f"JSON export saved to:\n{path}")
        except OSError as exc:
            self.show_error("Could not export data", exc)

    def backup_data(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Back up local database", str(Path.home() / "apply-assistant-backup.sqlite3"),
            "SQLite database (*.sqlite3)",
        )
        if not path:
            return
        try:
            self.database.backup_to(path)
            QMessageBox.information(self, "Backup complete", f"Database backup saved to:\n{path}")
        except (OSError, sqlite3.Error) as exc:
            self.show_error("Could not create database backup", exc)

    def open_prompt(self) -> None:
        PromptDialog(self).exec()

    def show_error(self, title: str, error: Exception) -> None:
        QMessageBox.critical(self, title, str(error))


def run() -> int:
    app = QApplication([])
    app.setApplicationName("Apply Assistant")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Apply Assistant")
    app.setStyle("Fusion")
    logo_path = Path(__file__).resolve().parent.parent / "resources" / "apply-assistant-logo.svg"
    if logo_path.is_file():
        app.setWindowIcon(QIcon(str(logo_path)))
    database = Database.default()
    window = MainWindow(database)
    window.show()
    result = app.exec()
    database.close()
    return result
