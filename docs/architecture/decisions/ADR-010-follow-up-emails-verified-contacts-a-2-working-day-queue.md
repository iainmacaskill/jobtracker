# ADR-010 — Follow-up emails: verified contacts, a 2-working-day queue, drafts only

**Status:** Accepted

**Context.** Applications go quiet; a short, well-timed nudge moves them forward.
But an automated nudger can embarrass (chasing a role that already replied or
rejected) or overstep (sending mail on the user's behalf).
**Decision.** Three cooperating parts, same app/agent split as ADR-008:

- **Contact resolver** (`contact_queue.py`). A follow-up needs a real recipient.
  Live roles without one surface in a *Needs a contact* queue; the agent resolves
  a **verified address only** — the user's Gmail (named sender) → LinkedIn/team
  page (verified named) → company site (monitored generic inbox) — recorded with
  its provenance in `contact_source`. **Never a constructed
  `first.last@domain` guess**; roles with no reachable address are marked
  `none` ("nudge via platform") rather than emailed speculatively.
- **Due queue** (`followup_queue.py`, the single source of the rule). A role is
  due once **2 working days** have passed since `date_applied`. The app section
  lists due roles with an **opt-out tick** (everything starts ticked;
  `follow_up`: 0 default / 1 ticked / 2 opted out).
- **Draft-only delivery.** The agent sweeps Gmail *first* — a reply beats a
  nudge (rejections flip status instead of getting mail). For the rest it writes
  a short, context/age-aware **Gmail draft** (`record_draft` files the link as
  `follow_up_draft`, status `Draft ready`). **The agent never sends.** The user
  reviews, edits and sends in Gmail, then `mark_sent` settles the row
  (`Sent <date>`), which drops it from the queue.

**Consequences.** Follow-ups are timely, personal and safe: every recipient is a
verified address, every email is human-reviewed and human-sent, and inbox
reality always overrides the clock. The trade-off is a two-step loop (queue →
ask Claude) instead of a send button — deliberate, per ADR-002 and the user's
human-in-the-loop preference.
