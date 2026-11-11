import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from apply_assistant.data import (
    Database,
    ImportValidationError,
    build_discovery_prompt,
    build_enrichment_prompt,
    build_researcher_profile_prompt,
)


def payload(**updates):
    data = {
        "schema_version": "1.0",
        "generated_at": "2026-11-11",
        "universities": [
            {
                "id": "university:north",
                "name": "North University",
                "country": "Exampleland",
                "website": "https://north.example.edu",
                "information_status": "user-provided",
            }
        ],
        "researchers": [
            {
                "id": "researcher:lee@university:north",
                "university_id": "university:north",
                "full_name": "Dr. Lee",
                "profile_url": "https://north.example.edu/lee",
            }
        ],
        "opportunities": [
            {
                "id": "opportunity:lee-phd",
                "researcher_id": "researcher:lee@university:north",
                "title": "PhD studentship",
                "deadline": "2027-01-15",
            }
        ],
        "publications": [
            {
                "id": "publication:lee-1",
                "researcher_id": "researcher:lee@university:north",
                "title": "A sample paper",
                "year": "2025",
            }
        ],
    }
    data.update(updates)
    return json.dumps(data)


class DatabaseImportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "test.sqlite3")

    def tearDown(self):
        self.database.close()
        self.temp_dir.cleanup()

    def test_import_adds_related_records_and_round_trips(self):
        result = self.database.import_json(payload())
        self.assertEqual(
            result,
            {
                "universities": {"added": 1, "updated": 0},
                "researchers": {"added": 1, "updated": 0},
                "opportunities": {"added": 1, "updated": 0},
                "publications": {"added": 1, "updated": 0},
                "applications": {"added": 0, "updated": 0},
            },
        )
        self.assertEqual(self.database.count("researchers"), 1)
        exported = json.loads(self.database.export_json())
        self.assertEqual(exported["researchers"][0]["university_id"], "university:north")
        self.assertEqual(exported["opportunities"][0]["researcher_id"], "researcher:lee@university:north")

    def test_only_matching_ids_update_and_missing_fields_are_preserved(self):
        self.database.import_json(payload())
        revised = {
            "schema_version": "1.0",
            "universities": [{"id": "university:north", "name": "North University Updated"}],
        }
        result = self.database.import_json(json.dumps(revised))
        university = self.database.get("universities", "university:north")
        self.assertEqual(result["universities"], {"added": 0, "updated": 1})
        self.assertEqual(university["name"], "North University Updated")
        self.assertEqual(university["country"], "Exampleland")
        self.assertEqual(self.database.count("researchers"), 1)
        self.assertEqual(self.database.count("opportunities"), 1)

    def test_same_name_with_a_different_id_is_added_not_merged(self):
        self.database.import_json(payload())
        second = {
            "schema_version": "1.0",
            "universities": [{
                "id": "university:north-campus",
                "name": "North University",
            }],
        }
        result = self.database.import_json(json.dumps(second))
        self.assertEqual(result["universities"], {"added": 1, "updated": 0})
        self.assertEqual(self.database.count("universities"), 2)

    def test_malformed_import_is_rejected_without_partial_writes(self):
        data = json.loads(payload())
        data["researchers"][0]["university_id"] = "missing-university"
        with self.assertRaises(ImportValidationError):
            self.database.import_json(json.dumps(data))
        self.assertEqual(self.database.count("universities"), 0)
        self.assertEqual(self.database.count("researchers"), 0)

    def test_duplicate_ids_and_unknown_fields_are_rejected(self):
        data = json.loads(payload())
        data["universities"].append(dict(data["universities"][0]))
        with self.assertRaisesRegex(ImportValidationError, "duplicates id"):
            self.database.preview_import(json.dumps(data))
        data = json.loads(payload())
        data["universities"][0]["replace_all"] = True
        with self.assertRaisesRegex(ImportValidationError, "unsupported field"):
            self.database.preview_import(json.dumps(data))

    def test_source_confirmed_records_need_a_url_and_check_date(self):
        data = {
            "schema_version": "1.0",
            "universities": [{
                "id": "university:north",
                "name": "North University",
                "information_status": "source-confirmed",
            }],
        }
        with self.assertRaisesRegex(ImportValidationError, "source_url and verified_on"):
            self.database.import_json(json.dumps(data))

    def test_preview_counts_without_writing(self):
        preview = self.database.preview_import(payload())
        self.assertEqual(preview["counts"]["universities"], {"added": 1, "updated": 0})
        self.assertEqual(self.database.count("universities"), 0)

    def test_backup_contains_the_current_database(self):
        self.database.import_json(payload())
        destination = Path(self.temp_dir.name) / "backup.sqlite3"
        self.database.backup_to(destination)
        backup = sqlite3.connect(destination)
        try:
            university_count = backup.execute("SELECT COUNT(*) FROM universities").fetchone()[0]
        finally:
            backup.close()
        self.assertEqual(university_count, 1)

    def test_existing_v3_database_is_migrated_without_losing_records(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.sqlite3"
        legacy = sqlite3.connect(legacy_path)
        try:
            legacy.execute(
                "CREATE TABLE universities (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
                "country TEXT NOT NULL DEFAULT '', website TEXT NOT NULL DEFAULT '', "
                "notes TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '', "
                "verified_on TEXT NOT NULL DEFAULT '', information_status TEXT NOT NULL "
                "DEFAULT 'user-provided', updated_at TEXT NOT NULL)"
            )
            legacy.execute(
                "CREATE TABLE researchers (id TEXT PRIMARY KEY, university_id TEXT NOT NULL, "
                "full_name TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', email TEXT NOT NULL "
                "DEFAULT '', profile_url TEXT NOT NULL DEFAULT '', research_interests TEXT "
                "NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL "
                "DEFAULT '', verified_on TEXT NOT NULL DEFAULT '', information_status TEXT "
                "NOT NULL DEFAULT 'user-provided', updated_at TEXT NOT NULL)"
            )
            legacy.execute(
                "CREATE TABLE opportunities (id TEXT PRIMARY KEY, researcher_id TEXT, "
                "title TEXT NOT NULL, deadline TEXT NOT NULL DEFAULT '', url TEXT NOT NULL "
                "DEFAULT '', details TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL "
                "DEFAULT '', verified_on TEXT NOT NULL DEFAULT '', information_status TEXT "
                "NOT NULL DEFAULT 'user-provided', updated_at TEXT NOT NULL)"
            )
            legacy.execute(
                "CREATE TABLE publications (id TEXT PRIMARY KEY, researcher_id TEXT NOT NULL, "
                "title TEXT NOT NULL, year TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', "
                "summary TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '', "
                "verified_on TEXT NOT NULL DEFAULT '', information_status TEXT NOT NULL "
                "DEFAULT 'user-provided', updated_at TEXT NOT NULL)"
            )
            legacy.execute(
                "INSERT INTO universities (id, name, updated_at) VALUES (?, ?, ?)",
                ("university:old", "Old University", "2026-01-01"),
            )
            legacy.execute(
                "INSERT INTO researchers (id, university_id, full_name, updated_at) "
                "VALUES (?, ?, ?, ?)",
                ("researcher:old", "university:old", "Dr. Existing", "2026-01-01"),
            )
            legacy.commit()
        finally:
            legacy.close()
        migrated = Database(legacy_path)
        try:
            self.assertEqual(migrated.get("researchers", "researcher:old")["age"], "")
            self.assertEqual(migrated.get("universities", "university:old")["name"], "Old University")
            self.assertEqual(migrated.count("applications"), 0)
        finally:
            migrated.close()

    def test_application_pipeline_and_private_outcome_fields_round_trip(self):
        source = {
            "schema_version": "2.0",
            "universities": [{"id": "university:north", "name": "North University"}],
            "researchers": [{
                "id": "researcher:lee",
                "university_id": "university:north",
                "full_name": "Dr. Lee",
            }],
            "opportunities": [{
                "id": "program:lee",
                "researcher_id": "researcher:lee",
                "title": "Doctoral program",
            }],
            "applications": [{
                "id": "application:lee",
                "university_id": "university:north",
                "researcher_id": "researcher:lee",
                "program_id": "program:lee",
                "title": "Doctoral program",
                "status": "submitted",
                "deadline": "2027-01-15",
                "next_task": "Prepare interview notes",
                "outcome": "waitlisted",
                "outcome_notes": "Private notes",
            }],
        }
        result = self.database.import_json(json.dumps(source))
        application = self.database.get("applications", "application:lee")
        self.assertEqual(result["applications"], {"added": 1, "updated": 0})
        self.assertEqual(application["outcome"], "waitlisted")
        self.assertEqual(application["outcome_notes"], "Private notes")
        exported = json.loads(self.database.export_json())
        self.assertEqual(exported["schema_version"], "2.0")
        self.assertEqual(exported["applications"][0]["outcome_notes"], "Private notes")

    def test_json_export_is_valid_import_input_for_unassigned_records(self):
        university_id = self.database.add_university("North University")
        self.database.add_opportunity("Unassigned program")
        self.database.add_application(university_id, "Unlinked application")
        exported = self.database.export_json()
        data = json.loads(exported)
        for records in data.values():
            if isinstance(records, list):
                for record in records:
                    self.assertTrue(all(isinstance(value, str) for value in record.values()))
        another_db = Database(Path(self.temp_dir.name) / "roundtrip.sqlite3")
        try:
            another_db.import_json(exported)
            self.assertEqual(another_db.count("opportunities"), 1)
            self.assertIsNone(another_db.rows("opportunities")[0]["researcher_id"])
            self.assertEqual(another_db.count("applications"), 1)
            self.assertIsNone(another_db.rows("applications")[0]["researcher_id"])
        finally:
            another_db.close()

    def test_university_and_researcher_deletion_counts_and_cascades(self):
        university_id = self.database.add_university("North University")
        researcher_id = self.database.add_researcher(university_id, "Dr. Lee")
        program_id = self.database.add_opportunity("Doctoral program", researcher_id)
        self.database.add_publication("A paper", researcher_id)
        self.database.add_application(
            university_id, "Doctoral application",
            researcher_id=researcher_id, program_id=program_id,
            outcome="accepted", outcome_notes="Private notes",
        )
        self.assertEqual(
            self.database.delete_counts("researchers", researcher_id),
            {"programs": 1, "publications": 1, "applications": 1},
        )
        self.database.delete_record("researchers", researcher_id)
        self.assertEqual(self.database.count("researchers"), 0)
        self.assertEqual(self.database.count("opportunities"), 0)
        self.assertEqual(self.database.count("publications"), 0)
        self.assertEqual(self.database.count("applications"), 0)
        self.assertEqual(
            self.database.delete_counts("universities", university_id),
            {"researchers": 0, "programs": 0, "publications": 0, "applications": 0},
        )
        self.database.delete_record("universities", university_id)
        self.assertEqual(self.database.count("universities"), 0)

    def test_program_deletion_removes_linked_private_application(self):
        university_id = self.database.add_university("North University")
        researcher_id = self.database.add_researcher(university_id, "Dr. Lee")
        program_id = self.database.add_opportunity("Doctoral program", researcher_id)
        application_id = self.database.add_application(
            university_id, "Doctoral application",
            researcher_id=researcher_id, program_id=program_id,
            outcome="accepted", outcome_notes="Private outcome",
        )
        self.assertEqual(self.database.delete_counts("opportunities", program_id), {"applications": 1})
        self.database.delete_record("opportunities", program_id)
        self.assertIsNone(self.database.get("opportunities", program_id))
        self.assertIsNone(self.database.get("applications", application_id))

    def test_mismatched_application_university_is_rejected_atomically(self):
        data = {
            "schema_version": "2.0",
            "universities": [
                {"id": "university:north", "name": "North University"},
                {"id": "university:south", "name": "South University"},
            ],
            "researchers": [{
                "id": "researcher:lee",
                "university_id": "university:north",
                "full_name": "Dr. Lee",
            }],
            "applications": [{
                "id": "application:lee",
                "university_id": "university:south",
                "researcher_id": "researcher:lee",
                "title": "Doctoral application",
            }],
        }
        with self.assertRaisesRegex(ImportValidationError, "different university"):
            self.database.import_json(json.dumps(data))
        self.assertEqual(self.database.count("universities"), 0)
        self.assertEqual(self.database.count("applications"), 0)

    def test_self_disclosed_personal_details_require_a_cited_verified_source(self):
        data = {
            "schema_version": "2.0",
            "universities": [{"id": "university:north", "name": "North University"}],
            "researchers": [{
                "id": "researcher:lee",
                "university_id": "university:north",
                "full_name": "Dr. Lee",
                "age": "48",
                "personal_info_status": "source-confirmed",
            }],
        }
        with self.assertRaisesRegex(ImportValidationError, "personal_info_source_url"):
            self.database.preview_import(json.dumps(data))


class DailyPromptTests(unittest.TestCase):
    def test_discovery_prompt_is_customizable_and_only_finds_names(self):
        prompt = build_discovery_prompt(
            "Biology", "Cell signaling", "Canada", "North U",
            "Microscopy", "2026-11-01 to 2026-11-11",
        )
        self.assertIn("Stage 1", prompt)
        self.assertIn("Discipline: Biology", prompt)
        self.assertIn("Topic/interests: Cell signaling", prompt)
        self.assertIn("does not produce import JSON", prompt)

    def test_enrichment_prompt_limits_personal_data_and_keeps_applications_private(self):
        prompt = build_enrichment_prompt(
            "Biology", "Cell signaling", "Canada", "North U", "Microscopy",
            "2026-11-01 to 2026-11-11", "Dr. Lee at North U",
        )
        self.assertIn("Stage 2", prompt)
        self.assertIn("Dr. Lee at North U", prompt)
        self.assertIn('"schema_version":"2.0"', prompt)
        self.assertIn("personally self-disclosed", prompt)
        self.assertIn('"applications":[]', prompt)
        self.assertIn("never published", prompt)

    def test_person_profile_prompt_targets_only_the_existing_researcher(self):
        prompt = build_researcher_profile_prompt({
            "id": "researcher:lee@university:north",
            "university_id": "university:north",
            "full_name": "Dr. Lee",
            "profile_url": "https://north.example.edu/lee",
            "research_interests": "Cell signaling",
            "notes": "Private note that must not be copied into an AI prompt.",
        })
        self.assertIn('"id": "researcher:lee@university:north"', prompt)
        self.assertIn('"university_id": "university:north"', prompt)
        self.assertIn("Return at most one researchers record", prompt)
        self.assertIn("stable ID", prompt)
        self.assertIn("applications", prompt)
        self.assertIn("Do not include age, favorite things", prompt)
        self.assertNotIn("Private note", prompt)


if __name__ == "__main__":
    unittest.main()
