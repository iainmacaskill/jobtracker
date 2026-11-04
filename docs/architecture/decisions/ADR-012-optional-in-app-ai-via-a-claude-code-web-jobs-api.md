# ADR-012 — Optional in-app AI via a Claude Code Web jobs API

**Status:** Accepted

**Context.** ADR-002 keeps the app free of LLMs and connectors: Claude works the
queues from outside (Cowork) and writes results back. That needs a desktop
session for every draft. When the tracker runs on a server it is reachable from
anywhere, but the drafting still is not. A self-hosted
[Claude Code Web](https://github.com/heng1234/claude-web) can expose a narrow,
key-authenticated **jobs API**: the server fixes each job's instructions, tools,
model and output schema ("profiles"); the caller only sends validated input.
**Decision.** Add an *optional* client (`claude_jobs.py`, UI in `ai_panel.py`),
active only when `CLAUDE_WEB_URL` and `CLAUDE_WEB_API_KEY` are set. It submits
profile-bound jobs (`job_search`, `job_fit_review`, `cv_tailor`, `cover_letter`,
`interview_prep`, `follow_up_email`, `cv_extract`), records them in an `ai_jobs`
table and polls them. CVs and cover letters are filed automatically as
`… (Claude).docx` next to the rule-based drafts (never overwriting them), and a
role queued as *Draft CV* settles to *CV Drafted* via `screening_queue`. Results
that replace something you own — fit notes, `profile.json`, new rows from a
search — wait for a click. You can upload your existing CV (`cv_upload.py`:
.docx / text PDF / .txt / .md); its text becomes `profile.json` via
`cv_extract`, or is used directly until you have a profile. The candidate's
profile is the only source of facts the server may use.
**Consequences.** Without the variables the app is exactly as before (ADR-001 /
ADR-002 hold; the Cowork prompts still work). With them, the deployment trusts
that server with the profile and job data it sends. Nothing is ever sent or
applied for: every output is a draft to review. Jobs cost money (estimated cost
is shown per job; the server enforces a daily budget per key) and take from
seconds to ~10 minutes, so the UI polls rather than blocks.
