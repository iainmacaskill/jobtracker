# Job Application Tracker

A small, local-first job-application tracker — **SQLite** for storage, a
**Streamlit** UI for browsing and editing. Track every role you find, the CV you
sent, where the application stands, and what happened next. Everything runs on
your machine; no accounts, no cloud, no data leaves your computer.

## Who this is for & what you need

This is a personal, local-first **starting point, not a one-click app** — a working
base you run and adapt. The easiest way to get going is to **point Claude Code at
this repo and ask it to set you up**; it'll handle the virtual environment,
dependencies and config.

- **To run the tracker itself:** Python 3 and a terminal (see [Quickstart](#quickstart)).
  It's a standalone local web app — your data stays on your machine.
- **To use the AI parts** (sweeping job boards, scoring fit, drafting tailored
  CVs/cover letters): Claude with the
  [job-hunt skill](examples/generate-job-hunt-skill.md) and the "Claude in Chrome"
  extension. The app and the agent are deliberately decoupled — see
  [ADR-002](docs/architecture/decisions/ADR-002-the-app-is-decoupled-from-the-agent-connector-layer.md) for why.
- **Bring your own profile:** copy `profile.example.json` to `profile.json`
  (git-ignored) — that's the only place your personal details live.

## Features

- 📊 **At-a-glance metrics** — totals by status, plus how many you applied to this week.
- ✏️ **Spreadsheet-style editing** — edit, add and delete roles inline, then save.
- 🔎 **Filtering** — by status, type, recruiter/company, date-found range, or free text.
- 🔗 **Stable de-duplication** — roles are keyed on the numeric job-id parsed from
  the link, so the same posting never gets logged twice.
- 🔄 **Live view** — the page reflects changes (including writes from other tools)
  within a few seconds.
- ⬇️ **Import / export** — pull new roles from an external database, import an
  existing spreadsheet, or export the whole tracker to CSV.
- 🔒 **Safe concurrency** — the database uses WAL mode, so a script can write while
  the app is open without the file-lock pain of an open spreadsheet.

## Quickstart

```bash
git clone <your-repo-url> jobtracker
cd jobtracker

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python seed.py                     # optional: load demo data to look around
streamlit run app.py
```

Streamlit opens the app at <http://localhost:8501>. Starting without `seed.py`
just gives you an empty tracker, ready for real data.

## Usage

- **Edit** any cell, **add** a role by typing into the blank bottom row, or
  **delete** by selecting a row and pressing ⌫ — then click **💾 Save changes**.
- Use the sidebar to **filter** and **🔄 Refresh**, or **⬇️ Export CSV**.
- See [USER_GUIDE.md](USER_GUIDE.md) for a walkthrough of the day-to-day workflow.

## Configuration

All machine-specific paths come from environment variables, optionally loaded
from a local `.env` file (copy `.env.example` to `.env`). Nothing is hardcoded.

| Variable | Purpose | Default |
|---|---|---|
| `JOBTRACKER_DB` | Tracker database location | `./jobs.db` |
| `JOBTRACKER_XLSX` | Spreadsheet for `migrate.py` to import | _(none)_ |
| `JOBTRACKER_IMPORT_DB` | External SQLite DB for `import_jobs.py` to pull from | _(none)_ |
| `JOBTRACKER_UPLOAD_DIR` | Where uploaded CVs are kept | `./uploads` |
| `CLAUDE_WEB_URL` | Claude Code Web server for the in-app AI tools (optional) | _(none)_ |
| `CLAUDE_WEB_API_KEY` | That server's jobs-API key (`cwk_…`) | _(none)_ |

## Claude assistant (optional)

The **🤖 Claude assistant** section lets you upload your current CV (.docx,
text-based PDF, .txt or .md) and keep your `profile.json`. If you run a
[Claude Code Web](https://github.com/heng1234/claude-web) server with the jobs
API, set `CLAUDE_WEB_URL` and `CLAUDE_WEB_API_KEY` and the same section can:

- turn your uploaded CV into `profile.json` (you review it before saving);
- search job boards for new roles, scored against your criteria and skipping
  ones already tracked (you pick which to add);
- review your fit for a role, tailor a CV, draft a cover letter, prepare you for
  an interview, or draft a follow-up email;
- draft every role queued as **Draft CV** in one click.

CVs and letters are saved as `… (Claude).docx` next to the template drafts.
Everything is a draft: nothing is sent or applied for. See
[ADR-012](docs/architecture/decisions/ADR-012-optional-in-app-ai-via-a-claude-code-web-jobs-api.md).

## Importing data

**From a spreadsheet** — `migrate.py` imports the `.xlsx` layout this project grew
out of (a workbook with `Pipeline` / `Applied` / `Not Applied` sheets). Point it
at your file and merge-import, de-duplicating by job-id:

```bash
python migrate.py --xlsx /path/to/tracker.xlsx --reset
```

**From another tool** — if a scraper or automation drops roles into a separate
SQLite database, `import_jobs.py` (or the **⬇️ Import new roles** button in the
app) merges the new ones in, leaving roles you've already edited untouched:

```bash
JOBTRACKER_IMPORT_DB=/path/to/incoming/jobs.db python import_jobs.py
```

Don't have an upstream yet? [examples/generate-job-hunt-skill.md](examples/generate-job-hunt-skill.md)
is a copy-paste prompt for building your own job-hunt skill with Claude — it
searches the boards you choose, drafts tailored CVs, and feeds new roles straight
into this tracker. (Requires Claude with skill creation and the "Claude in Chrome"
extension.)

## Schema (`jobs` table)

`date_found, title, company, type, rate, location, posted, link, fit_notes,
status, cv_version, date_applied, outcome` — plus a managed `id`, a
`source_job_id` (the numeric job-id parsed from the link, used for de-duplication)
and `created_at` / `updated_at` timestamps.

Canonical statuses: `Found, Draft CV, Draft CV & Cover Letter, CV Drafted,
Applied, Shortlisted, Interview, Offer, Pass, Rejected, Expired` (free text is
allowed too). Setting a role to **Draft CV** / **Draft CV & Cover Letter** in the
To-action queue generates the document(s) on save, then settles it to
**CV Drafted** — so you only spend effort on roles you choose to pursue.

## Project layout

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI |
| `config.py` | Environment-driven configuration |
| `db.py` | Schema + SQLite CRUD helpers (single source of truth) |
| `normalize.py` | Pure helpers: date parsing, job-id extraction, dedupe keys |
| `migrate.py` | Optional importer for a tracker spreadsheet |
| `import_jobs.py` | Import new roles from an external SQLite database |
| `tracker_add.py` | Add/update a role from a script or the shell (upsert) |
| `cv_builder.py` / `cover_letter.py` | On-demand CV / cover-letter draft generators |
| `profile.example.json` | Template for your CV profile (copy to git-ignored `profile.json`) |
| `seed.py` / `sample_jobs.csv` | Demo data |
| `examples/` | Copy-paste prompt to generate a job-hunt skill that feeds the tracker |
| `docs/` | Install guide, rollout backlog, and [architecture walkthrough & decision records](docs/architecture/README.md) |
| `tests/` | Pytest suite |

## Development

```bash
pip install -r requirements-dev.txt
pytest          # run the tests
ruff check .    # lint
```

## License

[MIT](LICENSE) — do what you like, no warranty.
