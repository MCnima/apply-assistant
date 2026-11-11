"""Local SQLite storage and safe, additive JSON imports."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


TABLE_FIELDS: dict[str, tuple[str, ...]] = {
    "universities": (
        "id", "name", "country", "website", "notes", "source_url",
        "verified_on", "information_status",
    ),
    "researchers": (
        "id", "university_id", "full_name", "title", "email", "profile_url",
        "research_interests", "notes", "source_url", "verified_on",
        "information_status", "age", "favorite_things", "linkedin_url",
        "google_scholar_url", "orcid_url", "other_social_links",
        "personal_info_source_url", "personal_info_verified_on",
        "personal_info_status",
    ),
    "opportunities": (
        "id", "researcher_id", "title", "deadline", "url", "details",
        "source_url", "verified_on", "information_status",
    ),
    "publications": (
        "id", "researcher_id", "title", "year", "url", "summary",
        "source_url", "verified_on", "information_status",
    ),
    "applications": (
        "id", "university_id", "researcher_id", "program_id", "title",
        "status", "deadline", "next_task", "next_task_date", "outcome",
        "outcome_notes", "notes", "source_url", "verified_on",
        "information_status",
    ),
}

LEGACY_TABLE_FIELDS = {
    table: tuple(fields) for table, fields in TABLE_FIELDS.items()
}
LEGACY_TABLE_FIELDS["researchers"] = (
    "id", "university_id", "full_name", "title", "email", "profile_url",
    "research_interests", "notes", "source_url", "verified_on",
    "information_status",
)
LEGACY_TABLE_FIELDS.pop("applications")
SCHEMA_VERSION = "2.0"
REQUIRED_FIELDS = {
    "universities": ("id", "name"),
    "researchers": ("id", "university_id", "full_name"),
    "opportunities": ("id", "title"),
    "publications": ("id", "researcher_id", "title"),
    "applications": ("id", "university_id", "title"),
}
INFO_STATUSES = {
    "source-confirmed", "user-provided", "unknown", "suggestion", "sample",
}
OPTIONAL_FIELDS = {
    table: tuple(field for field in fields if field not in REQUIRED_FIELDS[table])
    for table, fields in TABLE_FIELDS.items()
}
TABLE_SCHEMAS = {
    "universities": """
        id TEXT PRIMARY KEY, name TEXT NOT NULL, country TEXT NOT NULL DEFAULT '',
        website TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
        source_url TEXT NOT NULL DEFAULT '', verified_on TEXT NOT NULL DEFAULT '',
        information_status TEXT NOT NULL DEFAULT 'user-provided',
        updated_at TEXT NOT NULL
    """,
    "researchers": """
        id TEXT PRIMARY KEY, university_id TEXT NOT NULL REFERENCES universities(id),
        full_name TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
        email TEXT NOT NULL DEFAULT '', profile_url TEXT NOT NULL DEFAULT '',
        research_interests TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
        source_url TEXT NOT NULL DEFAULT '', verified_on TEXT NOT NULL DEFAULT '',
        information_status TEXT NOT NULL DEFAULT 'user-provided',
        updated_at TEXT NOT NULL
    """,
    "opportunities": """
        id TEXT PRIMARY KEY,
        researcher_id TEXT REFERENCES researchers(id),
        title TEXT NOT NULL, deadline TEXT NOT NULL DEFAULT '',
        url TEXT NOT NULL DEFAULT '', details TEXT NOT NULL DEFAULT '',
        source_url TEXT NOT NULL DEFAULT '', verified_on TEXT NOT NULL DEFAULT '',
        information_status TEXT NOT NULL DEFAULT 'user-provided',
        updated_at TEXT NOT NULL
    """,
    "publications": """
        id TEXT PRIMARY KEY,
        researcher_id TEXT NOT NULL REFERENCES researchers(id),
        title TEXT NOT NULL, year TEXT NOT NULL DEFAULT '',
        url TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
        source_url TEXT NOT NULL DEFAULT '', verified_on TEXT NOT NULL DEFAULT '',
        information_status TEXT NOT NULL DEFAULT 'user-provided',
        updated_at TEXT NOT NULL
    """,
    "applications": """
        id TEXT PRIMARY KEY,
        university_id TEXT NOT NULL REFERENCES universities(id),
        researcher_id TEXT REFERENCES researchers(id),
        program_id TEXT REFERENCES opportunities(id),
        title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'researching',
        deadline TEXT NOT NULL DEFAULT '', next_task TEXT NOT NULL DEFAULT '',
        next_task_date TEXT NOT NULL DEFAULT '', outcome TEXT NOT NULL DEFAULT '',
        outcome_notes TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
        source_url TEXT NOT NULL DEFAULT '', verified_on TEXT NOT NULL DEFAULT '',
        information_status TEXT NOT NULL DEFAULT 'user-provided',
        updated_at TEXT NOT NULL
    """,
}
APPLICATION_STATUSES = (
    "researching", "preparing", "submitted", "interview", "offer",
    "waitlisted", "rejected", "withdrawn",
)
OUTCOMES = ("", "accepted", "rejected", "waitlisted", "withdrawn")
PERSONAL_INFO_STATUSES = ("unknown", "user-provided", "source-confirmed")


class ImportValidationError(ValueError):
    """Raised when an import is malformed or has invalid references."""


def default_data_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "ApplyAssistant"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "apply-assistant"


def new_id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4()}"


def _validate_payload(payload: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise ImportValidationError("The JSON root must be an object.")
    schema_version = payload.get("schema_version")
    if schema_version not in {"1.0", SCHEMA_VERSION}:
        raise ImportValidationError(
            f"Unsupported or missing schema_version; expected \"1.0\" or \"{SCHEMA_VERSION}\"."
        )

    records: dict[str, list[dict[str, Any]]] = {}
    for table, fields in TABLE_FIELDS.items():
        if schema_version == "1.0" and table not in LEGACY_TABLE_FIELDS:
            records[table] = []
            continue
        rows = payload.get(table, [])
        if not isinstance(rows, list):
            raise ImportValidationError(f"\"{table}\" must be an array.")
        seen: set[str] = set()
        checked: list[dict[str, Any]] = []
        allowed = set(
            LEGACY_TABLE_FIELDS[table] if schema_version == "1.0" else fields
        )
        for index, row in enumerate(rows):
            label = f"{table}[{index}]"
            if not isinstance(row, dict):
                raise ImportValidationError(f"{label} must be an object.")
            extra = set(row) - allowed
            if extra:
                raise ImportValidationError(
                    f"{label} has unsupported field(s): {', '.join(sorted(extra))}."
                )
            for field in REQUIRED_FIELDS[table]:
                value = row.get(field)
                if not isinstance(value, str) or not value.strip():
                    raise ImportValidationError(f"{label}.{field} must be a non-empty string.")
            record_id = row["id"]
            if record_id in seen:
                raise ImportValidationError(f"{label} duplicates id \"{record_id}\".")
            seen.add(record_id)
            for field, value in row.items():
                if not isinstance(value, str):
                    raise ImportValidationError(f"{label}.{field} must be a string.")
            if (
                "information_status" in row
                and row["information_status"] not in INFO_STATUSES
            ):
                raise ImportValidationError(
                    f"{label}.information_status must be one of: {', '.join(sorted(INFO_STATUSES))}."
                )
            if row.get("information_status") == "source-confirmed":
                if not row.get("source_url", "").strip() or not row.get("verified_on", "").strip():
                    raise ImportValidationError(
                        f"{label} marked source-confirmed needs source_url and verified_on."
                    )
            has_personal_details = bool(
                row.get("age", "").strip() or row.get("favorite_things", "").strip()
            )
            if has_personal_details:
                if row.get("personal_info_status") != "source-confirmed":
                    raise ImportValidationError(
                        f"{label} age/favorite_things may only be imported when publicly "
                        "self-disclosed and source-confirmed."
                    )
                if (
                    not row.get("personal_info_source_url", "").strip()
                    or not row.get("personal_info_verified_on", "").strip()
                ):
                    raise ImportValidationError(
                        f"{label} age/favorite_things need "
                        "personal_info_source_url and personal_info_verified_on."
                    )
            elif row.get("personal_info_status") == "source-confirmed":
                raise ImportValidationError(
                    f"{label} cannot mark empty personal details source-confirmed."
                )
            if (
                "personal_info_status" in row
                and row["personal_info_status"] not in PERSONAL_INFO_STATUSES
            ):
                raise ImportValidationError(
                    f"{label}.personal_info_status must be one of: "
                    f"{', '.join(PERSONAL_INFO_STATUSES)}."
                )
            if table == "applications":
                if row.get("status") and row["status"] not in APPLICATION_STATUSES:
                    raise ImportValidationError(
                        f"{label}.status must be one of: {', '.join(APPLICATION_STATUSES)}."
                    )
                if row.get("outcome") and row["outcome"] not in OUTCOMES:
                    raise ImportValidationError(
                        f"{label}.outcome must be one of: {', '.join(OUTCOMES[1:])}."
                    )
            checked.append(dict(row))
        records[table] = checked

    envelope_fields = (
        {"schema_version", "generated_at", *LEGACY_TABLE_FIELDS}
        if schema_version == "1.0"
        else {"schema_version", "generated_at", *TABLE_FIELDS}
    )
    extra_envelope_fields = set(payload) - envelope_fields
    if extra_envelope_fields:
        raise ImportValidationError(
            "Unsupported top-level field(s): " + ", ".join(sorted(extra_envelope_fields)) + "."
        )
    return records


class Database:
    """Local repository for research leads and private application tracking."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    @classmethod
    def default(cls) -> "Database":
        return cls(default_data_dir() / "apply_assistant.sqlite3")

    def _create_schema(self) -> None:
        with self.connection:
            for table, schema in TABLE_SCHEMAS.items():
                self.connection.execute(f"CREATE TABLE IF NOT EXISTS {table} ({schema})")
            migrations = {
                "age": "TEXT NOT NULL DEFAULT ''",
                "favorite_things": "TEXT NOT NULL DEFAULT ''",
                "linkedin_url": "TEXT NOT NULL DEFAULT ''",
                "google_scholar_url": "TEXT NOT NULL DEFAULT ''",
                "orcid_url": "TEXT NOT NULL DEFAULT ''",
                "other_social_links": "TEXT NOT NULL DEFAULT ''",
                "personal_info_source_url": "TEXT NOT NULL DEFAULT ''",
                "personal_info_verified_on": "TEXT NOT NULL DEFAULT ''",
                "personal_info_status": "TEXT NOT NULL DEFAULT 'unknown'",
            }
            existing_columns = {
                row[1] for row in self.connection.execute("PRAGMA table_info(researchers)")
            }
            for column, definition in migrations.items():
                if column not in existing_columns:
                    self.connection.execute(
                        f"ALTER TABLE researchers ADD COLUMN {column} {definition}"
                    )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_researchers_university ON researchers(university_id)"
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_opportunities_researcher ON opportunities(researcher_id)"
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_publications_researcher ON publications(researcher_id)"
            )

    def close(self) -> None:
        self.connection.close()

    def rows(self, table: str) -> list[dict[str, Any]]:
        if table not in TABLE_FIELDS:
            raise ValueError(f"Unknown table: {table}")
        sort_column = {
            "universities": "name",
            "researchers": "full_name",
            "opportunities": "title",
            "publications": "title",
            "applications": "title",
        }[table]
        return [
            dict(row) for row in self.connection.execute(
                f"SELECT * FROM {table} ORDER BY {sort_column} COLLATE NOCASE, id"
            )
        ]

    def get(self, table: str, record_id: str) -> dict[str, Any] | None:
        if table not in TABLE_FIELDS:
            raise ValueError(f"Unknown table: {table}")
        row = self.connection.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
        return dict(row) if row else None

    def count(self, table: str) -> int:
        if table not in TABLE_FIELDS:
            raise ValueError(f"Unknown table: {table}")
        return int(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def add_university(
        self, name: str, country: str = "", website: str = "", **details: str,
    ) -> str:
        record_id = new_id("university")
        self._insert("universities", {
            "id": record_id, "name": name.strip(), "country": country.strip(),
            "website": website.strip(), "information_status": "user-provided",
            **details,
        })
        return record_id

    def add_researcher(
        self, university_id: str, full_name: str, title: str = "",
        profile_url: str = "", research_interests: str = "", **profile: str,
    ) -> str:
        record_id = new_id("researcher")
        self._insert("researchers", {
            "id": record_id, "university_id": university_id, "full_name": full_name.strip(),
            "title": title.strip(), "profile_url": profile_url.strip(),
            "research_interests": research_interests.strip(),
            "information_status": "user-provided",
            **profile,
        })
        return record_id

    def add_opportunity(
        self, title: str, researcher_id: str | None = None, **details: str,
    ) -> str:
        record_id = new_id("opportunity")
        self._insert("opportunities", {
            "id": record_id, "title": title.strip(), "researcher_id": researcher_id,
            "information_status": "user-provided", **details,
        })
        return record_id

    def add_publication(
        self, title: str, researcher_id: str, **details: str,
    ) -> str:
        record_id = new_id("publication")
        self._insert("publications", {
            "id": record_id, "title": title.strip(), "researcher_id": researcher_id,
            "information_status": "user-provided", **details,
        })
        return record_id

    def add_application(
        self, university_id: str, title: str, **details: str,
    ) -> str:
        record_id = new_id("application")
        for field in ("researcher_id", "program_id"):
            if not details.get(field):
                details[field] = None
        self._insert("applications", {
            "id": record_id, "university_id": university_id, "title": title.strip(),
            "status": "researching", "information_status": "user-provided",
            **details,
        })
        return record_id

    def update_record(self, table: str, record_id: str, values: dict[str, str]) -> None:
        if table not in TABLE_FIELDS:
            raise ValueError(f"Unknown table: {table}")
        allowed = set(TABLE_FIELDS[table]) - {"id"}
        if set(values) - allowed:
            raise ValueError("Update contains unsupported fields.")
        if not self.get(table, record_id):
            raise ValueError(f"Record no longer exists: {record_id}")
        if not values:
            return
        nullable_fields = {"researcher_id", "program_id"}
        normalized_values = {
            field: (None if field in nullable_fields and not value else value)
            for field, value in values.items()
        }
        fields = list(normalized_values)
        with self.connection:
            self.connection.execute(
                f"UPDATE {table} SET "
                + ", ".join(f"{field} = ?" for field in fields)
                + ", updated_at = ? WHERE id = ?",
                [normalized_values[field] for field in fields]
                + [datetime.now(timezone.utc).isoformat(timespec="seconds"), record_id],
            )

    def delete_counts(self, table: str, record_id: str) -> dict[str, int]:
        record = self.get(table, record_id)
        if not record:
            return {}
        if table == "universities":
            researcher_ids = [
                row[0] for row in self.connection.execute(
                    "SELECT id FROM researchers WHERE university_id = ?", (record_id,)
                )
            ]
            placeholders = ",".join("?" for _ in researcher_ids)
            program_ids = (
                [row[0] for row in self.connection.execute(
                    f"SELECT id FROM opportunities WHERE researcher_id IN ({placeholders})",
                    researcher_ids,
                )] if researcher_ids else []
            )
            application_scope = "university_id = ?"
            application_values: list[str] = [record_id]
            if researcher_ids:
                application_scope += " OR researcher_id IN (" + placeholders + ")"
                application_values.extend(researcher_ids)
            if program_ids:
                application_scope += " OR program_id IN (" + ",".join("?" for _ in program_ids) + ")"
                application_values.extend(program_ids)
            application_count = int(self.connection.execute(
                f"SELECT COUNT(*) FROM applications WHERE {application_scope}",
                application_values,
            ).fetchone()[0])
            return {
                "researchers": len(researcher_ids),
                "programs": len([
                    row for row in self.rows("opportunities")
                    if row.get("researcher_id") in researcher_ids
                ]),
                "publications": self._count_related(
                    "publications", "researcher_id", researcher_ids
                ),
                "applications": application_count,
            }
        if table == "researchers":
            program_ids = [
                row[0] for row in self.connection.execute(
                    "SELECT id FROM opportunities WHERE researcher_id = ?", (record_id,)
                )
            ]
            return {
                "programs": len(program_ids),
                "publications": self._count_related(
                    "publications", "researcher_id", [record_id]
                ),
                "applications": int(self.connection.execute(
                    "SELECT COUNT(*) FROM applications WHERE researcher_id = ?"
                    + (
                        " OR program_id IN (" + ",".join("?" for _ in program_ids) + ")"
                        if program_ids else ""
                    ),
                    [record_id, *program_ids],
                ).fetchone()[0]),
            }
        if table == "opportunities":
            return {"applications": self._count_applications("program_id", [record_id])}
        if table == "applications":
            return {}
        if table == "publications":
            return {}
        raise ValueError(f"Unknown table: {table}")

    def _count_related(self, table: str, key: str, ids: list[str]) -> int:
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        return int(self.connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {key} IN ({placeholders})", ids
        ).fetchone()[0])

    def _count_applications(self, key: str, ids: list[str]) -> int:
        return self._count_related("applications", key, ids)

    def delete_record(self, table: str, record_id: str) -> dict[str, int]:
        if table not in TABLE_FIELDS:
            raise ValueError(f"Unknown table: {table}")
        counts = self.delete_counts(table, record_id)
        with self.connection:
            if table == "universities":
                researcher_ids = [
                    row[0] for row in self.connection.execute(
                        "SELECT id FROM researchers WHERE university_id = ?", (record_id,)
                    )
                ]
                if researcher_ids:
                    placeholders = ",".join("?" for _ in researcher_ids)
                    program_ids = [
                        row[0] for row in self.connection.execute(
                            f"SELECT id FROM opportunities WHERE researcher_id IN ({placeholders})",
                            researcher_ids,
                        )
                    ]
                    application_scope = "university_id = ? OR researcher_id IN (" + placeholders + ")"
                    application_values: list[str] = [record_id, *researcher_ids]
                    if program_ids:
                        application_scope += " OR program_id IN (" + ",".join("?" for _ in program_ids) + ")"
                        application_values.extend(program_ids)
                    self.connection.execute(
                        f"DELETE FROM applications WHERE {application_scope}", application_values
                    )
                    self.connection.execute(
                        f"DELETE FROM publications WHERE researcher_id IN ({placeholders})",
                        researcher_ids,
                    )
                    self.connection.execute(
                        f"DELETE FROM opportunities WHERE researcher_id IN ({placeholders})",
                        researcher_ids,
                    )
                    self.connection.execute(
                        f"DELETE FROM researchers WHERE id IN ({placeholders})", researcher_ids
                    )
                else:
                    self.connection.execute(
                        "DELETE FROM applications WHERE university_id = ?", (record_id,)
                    )
                self.connection.execute("DELETE FROM universities WHERE id = ?", (record_id,))
            elif table == "researchers":
                program_ids = [
                    row[0] for row in self.connection.execute(
                        "SELECT id FROM opportunities WHERE researcher_id = ?", (record_id,)
                    )
                ]
                self.connection.execute(
                    "DELETE FROM applications WHERE researcher_id = ?", (record_id,)
                )
                if program_ids:
                    self.connection.execute(
                        f"DELETE FROM applications WHERE program_id IN "
                        f"({','.join('?' for _ in program_ids)})", program_ids
                    )
                self.connection.execute(
                    "DELETE FROM publications WHERE researcher_id = ?", (record_id,)
                )
                self.connection.execute(
                    "DELETE FROM opportunities WHERE researcher_id = ?", (record_id,)
                )
                self.connection.execute("DELETE FROM researchers WHERE id = ?", (record_id,))
            elif table == "opportunities":
                self.connection.execute(
                    "DELETE FROM applications WHERE program_id = ?", (record_id,)
                )
                self.connection.execute("DELETE FROM opportunities WHERE id = ?", (record_id,))
            else:
                self.connection.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))
        return counts

    def _insert(self, table: str, row: dict[str, Any]) -> None:
        fields = [field for field in TABLE_FIELDS[table] if field in row]
        values = [row[field] for field in fields]
        fields.append("updated_at")
        values.append(datetime.now(timezone.utc).isoformat(timespec="seconds"))
        with self.connection:
            self.connection.execute(
                f"INSERT INTO {table} ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)})",
                values,
            )

    def preview_import(self, json_text: str) -> dict[str, Any]:
        payload = _decode_json(json_text)
        records = _validate_payload(payload)
        self._validate_references(records)
        counts = {}
        for table, rows in records.items():
            counts[table] = {
                "added": sum(self.get(table, row["id"]) is None for row in rows),
                "updated": sum(self.get(table, row["id"]) is not None for row in rows),
            }
        return {"counts": counts, "records": records}

    def import_json(self, json_text: str) -> dict[str, dict[str, int]]:
        payload = _decode_json(json_text)
        records = _validate_payload(payload)
        added = {table: 0 for table in TABLE_FIELDS}
        updated = {table: 0 for table in TABLE_FIELDS}
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        try:
            with self.connection:
                self._validate_references(records)

                for table, rows in records.items():
                    for row in rows:
                        existing = self.connection.execute(
                            f"SELECT * FROM {table} WHERE id = ?", (row["id"],)
                        ).fetchone()
                        if existing is None:
                            values = dict(row)
                            values.setdefault("information_status", "user-provided")
                            values.setdefault("researcher_id", None)
                            for field in ("researcher_id", "program_id"):
                                if field in values and not values[field]:
                                    values[field] = None
                            fields = [field for field in TABLE_FIELDS[table] if field in values]
                            self.connection.execute(
                                f"INSERT INTO {table} ({', '.join(fields)}, updated_at) "
                                f"VALUES ({', '.join('?' for _ in fields)}, ?)",
                                [values[field] for field in fields] + [now],
                            )
                            added[table] += 1
                        else:
                            changed_fields = [
                                field for field in row if field != "id"
                            ]
                            if changed_fields:
                                changed_values = {
                                    field: (
                                        None if field in {"researcher_id", "program_id"}
                                        and not row[field] else row[field]
                                    )
                                    for field in changed_fields
                                }
                                self.connection.execute(
                                    f"UPDATE {table} SET "
                                    + ", ".join(f"{field} = ?" for field in changed_fields)
                                    + ", updated_at = ? WHERE id = ?",
                                    [changed_values[field] for field in changed_fields] + [now, row["id"]],
                                )
                                updated[table] += 1
        except sqlite3.IntegrityError as exc:
            raise ImportValidationError(
                f"Import could not be saved because a related record is missing or invalid: {exc}"
            ) from exc
        return {
            table: {"added": added[table], "updated": updated[table]}
            for table in TABLE_FIELDS
        }

    def _validate_references(self, records: dict[str, list[dict[str, Any]]]) -> None:
        university_ids = {
            row[0] for row in self.connection.execute("SELECT id FROM universities")
        } | {row["id"] for row in records["universities"]}
        researcher_ids = {
            row[0] for row in self.connection.execute("SELECT id FROM researchers")
        } | {row["id"] for row in records["researchers"]}
        researcher_by_id = {
            row["id"]: row for row in records["researchers"]
        }
        for row in records["researchers"]:
            if row["university_id"] not in university_ids:
                raise ImportValidationError(
                    f"researchers id \"{row['id']}\" references missing university "
                    f"\"{row['university_id']}\"."
                )
        for row in records["applications"]:
            if row["university_id"] not in university_ids:
                raise ImportValidationError(
                    f"applications id \"{row['id']}\" references missing university "
                    f"\"{row['university_id']}\"."
                )
            researcher_id = row.get("researcher_id")
            if researcher_id and researcher_id not in researcher_ids:
                raise ImportValidationError(
                    f"applications id \"{row['id']}\" references missing researcher "
                    f"\"{researcher_id}\"."
                )
            if researcher_id:
                application_researcher = researcher_by_id.get(researcher_id)
                if not application_researcher:
                    application_researcher = self.get("researchers", researcher_id)
                if (
                    application_researcher
                    and application_researcher["university_id"] != row["university_id"]
                ):
                    raise ImportValidationError(
                        f"applications id \"{row['id']}\" references a researcher "
                        "from a different university."
                    )
            program_id = row.get("program_id")
            if program_id:
                program = self.get("opportunities", program_id) or next(
                    (item for item in records["opportunities"] if item["id"] == program_id),
                    None,
                )
                if not program:
                    raise ImportValidationError(
                        f"applications id \"{row['id']}\" references missing program \"{program_id}\"."
                    )
                program_researcher_id = program.get("researcher_id")
                researcher_id = row.get("researcher_id") or program_researcher_id
                if researcher_id:
                    program_researcher = researcher_by_id.get(researcher_id)
                    if not program_researcher:
                        program_researcher = self.get("researchers", researcher_id)
                    if (
                        program_researcher
                        and program_researcher["university_id"] != row["university_id"]
                    ):
                        raise ImportValidationError(
                            f"applications id \"{row['id']}\" links a program or researcher "
                            "from a different university."
                        )
        for table in ("opportunities", "publications"):
            for row in records[table]:
                researcher_id = row.get("researcher_id")
                if researcher_id and researcher_id not in researcher_ids:
                    raise ImportValidationError(
                        f"{table} id \"{row['id']}\" references missing researcher "
                        f"\"{researcher_id}\"."
                    )

    def export_json(self) -> str:
        payload = {"schema_version": SCHEMA_VERSION, "generated_at": date.today().isoformat()}
        for table in TABLE_FIELDS:
            payload[table] = [
                {
                    field: ("" if row[field] is None else row[field])
                    for field in TABLE_FIELDS[table]
                }
                for row in self.connection.execute(
                    f"SELECT {', '.join(TABLE_FIELDS[table])} FROM {table} ORDER BY id"
                )
            ]
        return json.dumps(payload, indent=2, ensure_ascii=False)

    def backup_to(self, destination: str | Path) -> None:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        backup = sqlite3.connect(target)
        try:
            self.connection.backup(backup)
        finally:
            backup.close()


def _decode_json(json_text: str) -> Any:
    try:
        return json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ImportValidationError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc


def build_daily_prompt(
    discipline: str,
    topic: str,
    geography: str,
    university_scope: str,
    methods: str,
    date_range: str,
) -> str:
    """Backward-compatible alias for the first stage of the daily research flow."""
    return build_discovery_prompt(
        discipline, topic, geography, university_scope, methods, date_range,
    )


def _prompt_scope(
    discipline: str, topic: str, geography: str, university_scope: str,
    methods: str, date_range: str,
) -> dict[str, str]:
    values = {
        "discipline": discipline.strip() or "[your discipline]",
        "topic": topic.strip() or "[your topic or research interests]",
        "geography": geography.strip() or "[country or region]",
        "university_scope": university_scope.strip() or "[universities or \"discover suitable universities\"]",
        "methods": methods.strip() or "[methods, lab resources, or approaches]",
        "date_range": date_range.strip() or "[start date to end date]",
    }
    return values


def build_discovery_prompt(
    discipline: str,
    topic: str,
    geography: str,
    university_scope: str,
    methods: str,
    date_range: str,
) -> str:
    values = _prompt_scope(
        discipline, topic, geography, university_scope, methods, date_range,
    )
    return f"""Stage 1 — discover relevant researchers; do not generate detailed profiles yet.
Research window: {values['date_range']}
Discipline: {values['discipline']}
Topic/interests: {values['topic']}
Geography: {values['geography']}
University scope: {values['university_scope']}
Methods/resources: {values['methods']}

Find relevant university research groups and the names of researchers/professors who may supervise PhD work matching this scope. Prioritize official university, faculty, and lab sources. Return a concise list with only the university's official name and country, each researcher's full name, role if published, research-fit explanation, and direct official profile/source URLs. Do not invent people or claim suitability as fact. Leave out uncertain names rather than guessing. Do not guess email addresses or collect personal details at this stage. End with the date checked. This stage is for choosing names to enrich in Stage 2; it does not produce import JSON.
"""


def build_enrichment_prompt(
    discipline: str,
    topic: str,
    geography: str,
    university_scope: str,
    methods: str,
    date_range: str,
    selected_names: str,
) -> str:
    values = _prompt_scope(
        discipline, topic, geography, university_scope, methods, date_range,
    )
    names = selected_names.strip() or "[paste the researcher names selected from Stage 1]"
    return f"""Stage 2 — enrich only the selected names below with source-backed data.
Research window: {values['date_range']}
Discipline: {values['discipline']}
Topic/interests: {values['topic']}
Geography: {values['geography']}
University scope: {values['university_scope']}
Methods/resources: {values['methods']}

Selected names and Stage 1 source notes:
{names}

Verify each identity and affiliation on official public university/lab pages. Find relevant current PhD programs/openings and selected publications only when supported by official university, funder, or publisher sources. Cite the exact public URL and date checked for each record. Never invent names, affiliations, facts, IDs, deadlines, eligibility, funding, contact details, social links, or publications. Do not guess email addresses. Include age or favorite things only if the professor personally self-disclosed them in a public source; never infer or estimate personal details. If not publicly self-disclosed, leave those fields empty and mark personal_info_status "unknown". Include social profile links only when the researcher publicly provides them. Do not generate outreach questions. Admission and funding are never guaranteed.

Return ONLY one valid JSON object, no Markdown fences or commentary, using schema_version "{SCHEMA_VERSION}" and exactly these top-level keys: schema_version, generated_at, universities, researchers, opportunities, publications, applications. Use arrays (empty when no supported records exist). Include only new or materially updated university, researcher, program, and publication records, not an entire replacement database. Keep IDs stable across runs: normalized official university name; researcher name plus university ID; for programs/publications prefer stable official IDs or canonical URLs and otherwise deterministic normalized title IDs. Never change existing IDs. Applications are personal user-managed tracking records; do not create or update any application or outcome records from research. The app keeps those private locally and they are never published.

Each university: id, name (required), country, website, notes, source_url, verified_on, information_status.
Each researcher: id, university_id, full_name (required), title, email, profile_url, research_interests, notes, source_url, verified_on, information_status, age, favorite_things, linkedin_url, google_scholar_url, orcid_url, other_social_links, personal_info_source_url, personal_info_verified_on, personal_info_status. other_social_links is a string with one public profile per line. Use dedicated personal-info source/check fields only for publicly self-disclosed age/favorite things.
Each program: use the "opportunities" array; fields: id, title (required), researcher_id (optional), deadline, url, details, source_url, verified_on, information_status.
Each publication: id, researcher_id, title (required), year, url, summary, source_url, verified_on, information_status.
applications: always return an empty array; application tracking is private and not AI-generated.

All provided values must be strings. For unknown optional values use "". For `information_status`, use only "source-confirmed", "user-provided", "unknown", "suggestion", or "sample". Source-confirmed facts need source_url and verified_on. Source-confirmed personal information additionally needs personal_info_source_url and personal_info_verified_on. Do not include fields outside this contract.

Example shape:
{{"schema_version":"{SCHEMA_VERSION}","generated_at":"YYYY-MM-DD","universities":[],"researchers":[],"opportunities":[],"publications":[],"applications":[]}}
"""
