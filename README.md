# Apply Assistant

Apply Assistant is a local-first desktop workspace for organizing PhD research leads and privately tracking applications. The main research hierarchy is **university → researcher → research programs and publications**. Application milestones, tasks, outcomes, and outcome notes are stored locally on the user's device.

**Current version:** 3.1.0  
**License:** MIT

## Features

- Browse the university/researcher tree or open global lists of all universities, researchers, programs, publications, and applications.
- Open official/source links and see the information status and verification date for research records.
- Collapse or expand a researcher's program and publication sections; add or remove sourced records.
- Delete universities, researchers, programs, publications, or applications only after explicit confirmation. Confirmation lists linked records that will also be deleted. Deleting a university cascades through its researchers and their programs/publications/application records; deleting a researcher or program likewise removes their linked records.
- Record public profiles (LinkedIn, Google Scholar, ORCID, and other URLs). Age or favorite things are optional and should be entered only when the researcher has publicly self-disclosed them; those details have separate source and verification fields.
- Track applications by university with status, deadline, next task/date, outcome, and private outcome notes. Application records stay in the local database, are excluded from AI research prompts, and are not included in the public source repository.
- Generate two research prompts: Stage 1 discovers researcher names and public source URLs; Stage 2 enriches only selected names into structured, source-backed university, researcher, program, and publication data.
- Preview imports before applying them. Importing is additive: new stable IDs add records, matching IDs update only included fields, and omitted records/fields are retained. The whole import is validated and committed transactionally.
- Export a JSON copy or create a SQLite backup.

AI output is not independently verified by the app. Check cited sources yourself, especially deadlines, eligibility, funding, social links, and personal details. The app does not contact an AI service, scrape websites, send email, or guarantee admission/funding.

## Windows setup

Requires Python 3.10 or newer and Windows.

```powershell
cd .\apply-assistant
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m apply_assistant
```

The database is at `%LOCALAPPDATA%\ApplyAssistant\apply_assistant.sqlite3`. Opening an existing database upgrades it in place while preserving existing records and adding the new profile/application fields. Back up the database before replacing it or testing a migration.

## Daily AI data workflow

1. Select **Daily AI prompt** and choose Stage 1. Fill in the scope, copy the prompt into an AI tool, and review its researcher names and source links.
2. Select the researchers you want, switch to Stage 2, and paste those names/source notes into the names field. Copy the enrichment prompt.
3. Check every source and correct/remove unsupported facts. Save the AI's JSON as a `.json` file.
4. Choose **Import JSON**, inspect the preview counts, and confirm only if the changes are right. The AI prompt always excludes private application/outcome records.
5. Export or back up regularly.

Stage 2 uses schema version `2.0`; older `1.0` imports remain supported. Stable IDs are required. Reuse an ID only for the same record; same-name records with different IDs remain separate. Researchers need a `university_id`; publications need a `researcher_id`; programs may be unassigned. Applications require a `university_id`, and may optionally link a researcher and program. Omitted fields on matching records are not overwritten. Personal application data is local-only, but a user-selected JSON export contains all database records; protect that export accordingly.

Top-level JSON shape:

```json
{
  "schema_version": "2.0",
  "generated_at": "YYYY-MM-DD",
  "universities": [],
  "researchers": [],
  "opportunities": [],
  "publications": [],
  "applications": []
}
```

For exact allowed fields, use the Stage 2 prompt in the app. Research record statuses are `source-confirmed`, `user-provided`, `unknown`, `suggestion`, or `sample`; source-confirmed facts need `source_url` and `verified_on`. Self-disclosed personal details need `personal_info_source_url`, `personal_info_verified_on`, and a separate `personal_info_status`. Unknown optional text values should be empty strings. Unknown fields are rejected rather than silently discarded.

## Test and compile

```powershell
python -m unittest discover -s tests -v
python -m compileall -q apply_assistant tests run_app.py
```

## Optional Windows executable

After installing the requirements, install PyInstaller and package the app:

```powershell
pip install pyinstaller
pyinstaller --noconfirm --windowed --name "Apply Assistant" --collect-all PySide6 --add-data "resources;resources" run_app.py
```

Test a packaged executable on a clean Windows machine before distributing it. User data is saved outside the application bundle in local app data.
