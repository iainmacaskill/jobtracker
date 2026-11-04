# Architecture & Decisions

How the Job Application Tracker is put together, what it deliberately does and
doesn't do, and where the detailed walkthrough and decision records live.

## The app in one paragraph

A local-first, single-user application tracker: a **SQLite** database (`jobs.db`)
holds the roles, and a **Streamlit** UI reads and edits them. Optional importers
feed it from a spreadsheet or an external database. It runs entirely on your
machine — no accounts, no server, no data leaves the computer.

## Capability boundary (read this first)

The **Streamlit app is a standalone local web app.** It can talk to its own
SQLite database and the local filesystem — and not much else. In particular it
**cannot**:

- call MCP connectors (Gmail, Jira, …),
- invoke Claude / Cowork or any LLM,
- reach a remote service without credentials wired in.

Anything that needs those lives in the **agent layer** — Claude in Cowork, the
job-hunt skill, scheduled routines. Those produce data (drafted CVs, rows in a
database) that the app then reads. The app and the automation are deliberately
**decoupled**: the agent writes, the app displays and edits.

This boundary is why several "buttons" in this project are deep-links or
import-from-database steps rather than direct integrations.


---

## Where the rest lives

The full architecture walkthrough — context and container diagrams, the module
dependency graph, data schema, status lifecycle, and a sequence diagram per
workflow — is in [`docs/architecture/`](architecture/README.md). Start at its
README; it is written to be read top-down.

Decision records (ADR-001 onwards) are one file each under
[`docs/architecture/decisions/`](architecture/decisions/README.md). Add new
decisions there, using the template in that folder.
