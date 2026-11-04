# ADR-004 — Status-driven pipeline with a derived "To action" queue

**Status:** Accepted

**Context.** The core job is tracking each role through a pipeline.
**Decision.** A single `status` field drives everything. The **To action** view
is *derived* (roles whose status isn't yet actioned), not a separate list — a
role leaves it automatically when its status changes. Closed or
not-to-be-actioned statuses (`Pass`, `Rejected`, `Expired`, …) drop a role out of
the queue.
**Consequences.** No manual "move between lists"; the queue and the metrics stay
consistent with status by construction.
