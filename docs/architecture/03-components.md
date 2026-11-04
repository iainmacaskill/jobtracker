<!-- archdoc:manual -->

# Components (C4 level 3)

The modules inside the code and how they depend on each other. The graph is
generated from the import statements — see
[generated/dependencies.md](generated/dependencies.md) for the edge table and
[generated/modules.md](generated/modules.md) for every public symbol.

<!-- archdoc:include generated/dependencies.md -->
*On GitHub, open [dependencies.md](generated/dependencies.md) for the diagram; the built walkthrough inlines it here.*
<!-- /archdoc:include -->

## Layers, top to bottom

| Layer | Modules | Rule |
|---|---|---|
| ui | `app` | The only module that imports from every layer. Holds no business rules that another layer owns (e.g. it imports `followup_queue.is_due` rather than re-deriving it) |
| queues | `screening_queue`, `contact_queue`, `followup_queue` | Agent-side. Depend on `db` only; take an explicit connection so tests control the database |
| documents | `cv_builder`, `screening_cv`, `interview_cv`, `cover_letter`, `cv_preview` | Turn a role + `profile.json` into a file. `cv_builder` owns profile loading and sector detection; the two CV renderers build on it |
| ingest | `tracker_add`, `import_jobs`, `migrate`, `seed` | Entry points that write rows. All go through `db.upsert_job` and `normalize` |
| data | `db`, `normalize` | `db` is the schema (`FIELDS`, `APP_COLUMNS`, `STATUSES`, `SCHEMA`) and CRUD; `normalize` is pure helpers with no imports |
| config | `config` | Paths from environment / `.env`. Imports nothing local |

## Things worth knowing

- **`FIELDS` vs `APP_COLUMNS`** (`db.py`): `FIELDS` are importable role data;
  `APP_COLUMNS` (`contact_email`, `follow_up*`, `archived`, …) are app-managed
  state that importers must never overwrite. `_ensure_columns` adds new columns to
  an existing database on startup, so the schema migrates forward automatically.
- **Status is the pipeline** ([ADR-004](decisions/ADR-004-status-driven-pipeline-with-a-derived-to-action-queue.md)):
  every queue is a *derived view* over `status` plus a few flags — see the
  [status lifecycle](generated/states.md). Nothing stores "which queue am I in".
- **Idempotent writes** ([ADR-005](decisions/ADR-005-de-duplicate-on-a-stable-job-id-importers-feed-the-database.md)):
  `db.upsert_job` keys on `source_job_id`, parsed from the advert link by
  `normalize.parse_job_id`, so the agent can re-run a sweep safely.

Related decisions: [ADR-004](decisions/ADR-004-status-driven-pipeline-with-a-derived-to-action-queue.md), [ADR-005](decisions/ADR-005-de-duplicate-on-a-stable-job-id-importers-feed-the-database.md), [ADR-009](decisions/ADR-009-interview-cv-a-designed-html-pdf-built-in-house.md)
