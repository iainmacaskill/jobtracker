"""Central configuration.

All environment-specific paths are read from environment variables (optionally
loaded from a local ``.env`` file) so nothing machine-specific is hardcoded in
the source. Copy ``.env.example`` to ``.env`` to override the defaults.
"""

from __future__ import annotations

import os
from pathlib import Path

try:  # python-dotenv is optional — plain environment variables work without it.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent


def _path_env(name: str, default: Path | None) -> Path | None:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else default


# The tracker database — the canonical store. Defaults to ./jobs.db in the repo.
DB_PATH = _path_env("JOBTRACKER_DB", PROJECT_ROOT / "jobs.db")

# Optional: a spreadsheet to import via migrate.py. No default — pass --xlsx or
# set JOBTRACKER_XLSX to your own file.
XLSX_PATH = _path_env("JOBTRACKER_XLSX", None)

# Optional: an external SQLite database that some other tool writes new roles
# into (e.g. a scraper or automation), for import_jobs.py to pull from.
IMPORT_DB_PATH = _path_env("JOBTRACKER_IMPORT_DB", None)

# Where generated cover-letter drafts are saved. Defaults to ./cover_letters.
COVER_LETTER_DIR = _path_env("JOBTRACKER_COVER_LETTER_DIR", PROJECT_ROOT / "cover_letters")

# Where generated CV drafts are saved. Defaults to ./cvs.
CV_DIR = _path_env("JOBTRACKER_CV_DIR", PROJECT_ROOT / "cvs")

# Where the job-hunt agent drops tailored CVs. Defaults to ./resumes. The
# in-app CV preview searches this folder first, then CV_DIR.
RESUME_DIR = _path_env("JOBTRACKER_RESUME_DIR", PROJECT_ROOT / "resumes")

# Profile data the in-app CV builder reads (kept out of the repo — copy
# profile.example.json to profile.json and fill it in).
PROFILE_PATH = _path_env("JOBTRACKER_PROFILE", PROJECT_ROOT / "profile.json")

# Where uploaded CVs (the original file plus its extracted text) are kept.
UPLOAD_DIR = _path_env("JOBTRACKER_UPLOAD_DIR", PROJECT_ROOT / "uploads")

# Optional: a self-hosted Claude Code Web server whose jobs API drafts CVs, cover
# letters, fit reviews, interview prep and follow-ups, and searches for roles
# (ADR-012). Leave the key unset and the tracker stays fully local, as before.
CLAUDE_WEB_URL = os.environ.get("CLAUDE_WEB_URL", "").strip().rstrip("/")
CLAUDE_WEB_API_KEY = os.environ.get("CLAUDE_WEB_API_KEY", "").strip()
