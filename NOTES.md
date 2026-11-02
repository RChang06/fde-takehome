# Projects API notes

Base: `https://fde-takehome-projects-api-hkbn2zj27a-ue.a.run.app/api/v1`
Probed with a throwaway project (created then deleted). Seed data untouched.

## Real endpoint map

The listed paths drop the ids. Real routes put them in the path.

| Listed | Real | Body | Returns |
|---|---|---|---|
| GET /health | GET /health | | `{"status":"ok"}` |
| GET /proj | GET /proj?from=0&take=5 | | `{from, take, total, projects[]}` |
| GET /proj/ | GET /proj/{pid} | | project |
| POST /proj/new | POST /proj/new | JSON `{title, description?, status?}` | 201 project |
| PUT /proj/modify | PUT /proj/{pid}/modify | JSON, any of `title, description, status` | project |
| DELETE /proj/remove | DELETE /proj/{pid}/remove | | `{"removed": pid}` |
| POST /proj/touch | POST /proj/{pid}/touch | `{}` | project, `updated_at` = now |
| GET /proj/items | GET /proj/{pid}/items | | `{items[]}` |
| POST /proj/items/add | POST /proj/{pid}/items/add | JSON `{task, who?, by?}` | 201 item |
| POST /proj/items/mark | POST /proj/{pid}/items/{tid}/mark | JSON `{"flag":"yes"\|"no"}` | item |
| DELETE /proj/items/yank | DELETE /proj/{pid}/items/{tid}/yank | | `{"removed": tid}` |

## Data shapes

- project: `id` (proj_xxxxxx), `title`, `description`, `status`, `items[]`, `updated_at` (epoch ms)
- item (todo): `id` (todo_xxxxxx), `task`, `who`, `by` (due, epoch ms), `done` (bool)
- status enum: `kickoff, wip, blocked, wrapped, dropped`
- seed: 7 projects, 18 todos, people `andy, betty, carlos, dan`

## Quirks

1. **Paths in the brief are wrong**: ids go in the path (`/proj/{pid}/items/{tid}/mark`). `/proj/items` is read as a project called "items" (`no such project`).
2. **Pagination is silent and capped**: default and max `take` is 5, `total` is 7. A naive `GET /proj` misses 2 projects. `take>5` is clamped without error. `from=-1` returns empty, no error.
3. **Field names differ from the brief**: todos are `items`, person is `who`, due date is `by`, completion is `done`.
4. **Timestamps are epoch milliseconds**, not dates. Seed due dates are relative to server boot, so "late" shifts if the server restarts.
5. **mark wants `{"flag":"yes"|"no"}`**, not a boolean. `true`, `"YES"`, `{"done":true}` and query string all fail with `flag must be 'yes' or 'no'`. Idempotent (yes twice is fine).
6. **`updated_at` only moves on `touch`**. modify, items/add, mark and yank do NOT bump it. So "what changed this week" cannot come from `updated_at`, and every seeded project has the same `updated_at`.
7. **`by` is not validated**: accepts `"2026-11-06"`, `"next friday"`, or a number, and stores it as is. Mixed types in one list.
8. **`by` defaults to now** when omitted, so a todo with no due date is instantly "late".
9. **`who` is free text, case sensitive, default `""`**: `Dan` and `dan` are different people. Unknown fields (`person`, `due`) are silently ignored.
10. **`title` can be modified to `""`** (only required on create). Unknown modify fields (`updated_at`) are silently ignored.
11. **JSON only**: form or text bodies give `title is required`. POST with no body at all gets a Google front end `411 Length Required` HTML page, not JSON.
12. **Errors are `{"error": "..."}`**, mostly 400/404/405. 404 is used for both bad routes (`not found`) and missing records (`no such project` / `no such item`).
13. **No lookup by name**: everything needs `proj_`/`todo_` ids. Humans and LLMs say "the launch project".
14. **Data is in memory**: resets on restart, ids change.

## What this means for the build

- The wrapper must: page through everything, translate names to ids (fuzzy title match), send `flag` yes/no, normalize `by` to a real date (and reject garbage on write), lowercase `who`, and call `touch` after every write so `updated_at` means something.
- Carlos's "what changed this week" needs our own snapshot and diff, because the API keeps no history.
- Late = `done == false and by < now`, after normalizing `by`.

## Decisions

- their server restarted mid build: every id changed (proj_b66f07 -> proj_8d2213). proof that name lookup beats ids
- wrapper, report, webhook, mcp server built and tested against the live api (scratch project for writes, test changes reverted)
- shared chat at /chat (one api key, claude-opus-5-5, low effort). replies are tool output verbatim, enforced in code after claude paraphrased in testing
- strict exact matching for andy's webhook (unattended), loose matching kept for the chat (a human sees every reply)
