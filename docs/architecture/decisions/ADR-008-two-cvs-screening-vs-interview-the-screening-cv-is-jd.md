# ADR-008 — Two CVs (screening vs interview); the screening CV is JD-driven via an agent queue

**Status:** Accepted

**Context.** The first hurdle is automated screening — keyword/semantic matching of
the CV against the job description — and recruiters later search the ATS by exact
terms. A CV that reads well to a human and a CV that parses well for a machine have
*opposite* requirements: design (columns, tables, graphics) helps the human but
breaks ATS parsers.
**Decision.** Split the document in two.

- **Screening CV** — optimised to pass screening. Plain, single-column, standard
  headings, real text, **no tables/graphics** (`screening_cv.py`). Its content is
  **driven by the specific JD**: the advert's terminology is mirrored against the
  candidate's *genuine* experience, and `keyword_coverage()` reports real gaps. The
  honesty rule is absolute — only keywords for skills the candidate actually has;
  no invented terms (they get caught and collapse at interview). The user always
  reviews before sending.
- **Interview CV** — the polished, human-facing document (design/layout). Out of
  scope for now; this is where any "good-looking" work belongs.

**Delivery — agent queue (not an in-app button).** Reading a JD and authoring the
CV needs an LLM, which the app does not have (ADR-002). So setting a role to
`Draft CV` in the app is a **queue marker only** — it writes nothing. Claude
processes the queue (`screening_queue.list_queue`): reads each JD, writes the
screening CV, then `screening_queue.record_result` files the filename + coverage
back onto the role and settles it to `CV Drafted`.
**Consequences.** Keyword optimisation lives where the JD and the LLM are (the
agent), the app stays a pure local viewer/editor, and the offline sector-aware cut
(ADR-007) remains available as a no-JD fallback. The trade-off is that drafting is
*asynchronous* — it happens when Claude next runs, not on click.
