# ADR-003 — Gmail integration is minimal and outbound-focused

**Status:** Accepted

**Context.** Gmail can in principle tell us about application responses. But for
the way this tracker is actually used:

- genuine recruiter interest arrives **by phone first**, with email only as a
  follow-up — so an "you got a response" alert reports something already known;
- **rejections are not of interest**;
- the thing that matters is **knowing applications are going out** — it's a
  numbers game.

**Decision.**

- Keep a lightweight **"Search Gmail for replies"** deep-link in the app (it opens
  a pre-built Gmail search; it reads nothing and changes nothing).
- **Do not** build automated inbox *response*-reading into the app or a routine —
  low return for this workflow.
- If Gmail is ever automated, point it at the **outbound** side: confirming an
  application actually sent and auto-stamping `Applied` + date, which keeps the
  throughput metrics honest without manual entry.

**Consequences.** We avoid building an OAuth/response-parsing feature that would
mostly surface noise or already-known news. On-demand inbox scanning is still
available by simply asking Claude in Cowork (which has the Gmail connector). The
app's value stays centred on the **apply-and-track loop**, not response-chasing.
