# Server patch: `answer_draft` profile

`claude-web-answer_draft.patch` adds one job profile, `answer_draft`, to the Claude
Code Web jobs API (`sadorect/claude-web-auth`). It is **not applied** to the live
server; the tracker's "Draft with Claude" button stays disabled until the server
offers the profile.

Made against `claude-web-auth` `main` at `a37e035`. It changes
`claude_web/jobs/jobhunt.py`, `docs/JOBS-API.md` and `tests/test_jobs_jobhunt.py`.

## What the profile does

Input: the role, your `candidate` profile (the tracker adds `story_bank`), one
`question`, and optionally `why_asked`, `answer_outline`, `story_ids`,
`current_answer` and `spoken_minutes` (1-3). No tools, $0.50 budget.

Output: `answer` (first person, as spoken), `fill_ins[]`, `gaps`, `stories_used[]`,
`evidence_used`, `honesty_check`, `word_count`. Where a number, outcome or tool is
not in your profile or stories, the answer carries a visible `[FILL IN: ...]` marker
instead of an invention. If you supply `current_answer`, your wording and facts win.

## Deploying it (you decide when)

1. In a checkout of `claude-web-auth`: `git apply /path/to/claude-web-answer_draft.patch`
2. Run its tests: `pytest tests/test_jobs_jobhunt.py tests/test_jobs_api.py`
3. Deploy, then enable `answer_draft` on the tracker's API key (the jobs API admin
   has a set-profiles action for existing keys).
4. Reload the Interview prep page; the button enables itself within 5 minutes.

## What was and was not checked

Checked: the patch applies cleanly to `a37e035`, and 18 profile tests pass
(registration, schema, prompts, input validation, no-tools). **Not run:** the two
tests in those files that need the HTTP test client, and any live job. The first real
draft will be the first end-to-end test of the prompt.
