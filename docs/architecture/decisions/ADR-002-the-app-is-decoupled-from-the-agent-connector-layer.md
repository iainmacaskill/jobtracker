# ADR-002 — The app is decoupled from the agent/connector layer

**Status:** Accepted

**Context.** Useful capabilities (search job boards, read Gmail, write Jira,
draft CVs/cover letters with an LLM) require MCP connectors or an LLM. A local
Streamlit process can reach none of these.
**Decision.** Keep the app to local data + UI. Capabilities that need an agent
run in Cowork / the job-hunt skill / scheduled routines and hand results to the
app via the database or files. In-app "buttons" for agent-side capabilities are
either (a) deep-links that open the relevant tool, or (b) imports of data an
agent produced.
**Consequences.** An honest, low-coupling design that works offline; the
trade-off is that "live" agent actions are triggered by asking Claude (or by a
schedule), not by a web button.
