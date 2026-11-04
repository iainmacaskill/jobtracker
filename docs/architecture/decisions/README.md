<!-- archdoc:manual -->

# Decision records

Architecture Decision Records: one file per decision, numbered in the order
they were made. Start a new one from [ADR-template.md](ADR-template.md).

| ADR | Title | Status |
|---|---|---|
| ADR-001 | [Local-first, single-user (SQLite + Streamlit)](ADR-001-local-first-single-user-sqlite-streamlit.md) | Accepted |
| ADR-002 | [The app is decoupled from the agent/connector layer](ADR-002-the-app-is-decoupled-from-the-agent-connector-layer.md) | Accepted |
| ADR-003 | [Gmail integration is minimal and outbound-focused](ADR-003-gmail-integration-is-minimal-and-outbound-focused.md) | Accepted |
| ADR-004 | [Status-driven pipeline with a derived "To action" queue](ADR-004-status-driven-pipeline-with-a-derived-to-action-queue.md) | Accepted |
| ADR-005 | [De-duplicate on a stable job-id; importers feed the database](ADR-005-de-duplicate-on-a-stable-job-id-importers-feed-the-database.md) | Accepted |
| ADR-006 | [SQLite in WAL mode; configuration via environment](ADR-006-sqlite-in-wal-mode-configuration-via-environment.md) | Accepted |
| ADR-007 | [Draft CVs on demand, not during the sweep](ADR-007-draft-cvs-on-demand-not-during-the-sweep.md) | Accepted |
| ADR-008 | [Two CVs (screening vs interview); the screening CV is JD-driven via an agent queue](ADR-008-two-cvs-screening-vs-interview-the-screening-cv-is-jd.md) | Accepted |
| ADR-009 | [Interview CV: a designed HTML→PDF, built in-house](ADR-009-interview-cv-a-designed-html-pdf-built-in-house.md) | Accepted |
| ADR-010 | [Follow-up emails: verified contacts, a 2-working-day queue, drafts only](ADR-010-follow-up-emails-verified-contacts-a-2-working-day-queue.md) | Accepted |
| ADR-011 | [Archive for ended/closed roles (not deletion)](ADR-011-archive-for-ended-closed-roles-not-deletion.md) | Accepted |
| ADR-012 | [Optional in-app AI via a Claude Code Web jobs API](ADR-012-optional-in-app-ai-via-a-claude-code-web-jobs-api.md) | Accepted |
| ADR-013 | [Interview prep as per-role data on its own page](ADR-013-interview-prep-as-per-role-data-on-its-own-page.md) | Accepted |
