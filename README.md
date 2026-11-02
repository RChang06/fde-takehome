# projects kit

One wrapper (`projects_kit/client.py`) fixes the Projects API's quirks once (paging, ids, `flag` yes/no,
dates, `touch`, read-back verify). Each person gets a thin front end on top. Quirks are in [NOTES.md](NOTES.md).

```
uv sync
```

| Who | What | Run |
|---|---|---|
| Andy | webhook for zapier / n8n / make / gumloop | `uv run uvicorn projects_kit.webhook:app --port 8000` |
| Carlos | weekly summary, Slack ready | `uv run python -m projects_kit.report` |
| Dan, Betty | talk to projects in Claude (MCP) | config below |
| Betty's teammates | shared web chat, one API key | same webhook server, open `/chat` |

Every failure has the same shape:

```
✗ <tool> failed at <RESOLVE|VALIDATE|API|VERIFY>
why: <cause, with the input>
next: <one thing to try>
```

## Andy: mark a todo done from any automation

Add a "Webhooks by Zapier" (or n8n "HTTP Request") step:

- Method `POST`, URL `https://<tunnel>/andy/complete`. JSON or form data both work (Zapier's default is form), no header needed.
- Body JSON: `{"project": "Spring product launch", "task": "Finalize launch blog post"}`. Add `"done": false` to undo.
- Names must be exact (case doesn't matter). Strict on purpose: nobody watches a zap, so a wrong partial match
  would go unnoticed. A partial name fails with `use the full name: "..."`. Get exact names from the chat ("list projects").
- Success is 200 with `✓ Marked ...`. Any failure is non 2xx with a diagnosis, so the zap shows as failed.

Public URL for the tools: `cloudflared tunnel --url http://localhost:8000`

```
curl -X POST localhost:8000/andy/complete -H "content-type: application/json" \
  -d '{"project":"Spring product launch","task":"Finalize launch blog post"}'
```

## Carlos: weekly summary

The API keeps no history, so each run saves a snapshot in `snapshots/` and compares with the one closest to
7 days ago. The first run only saves a baseline.

- Stuck: status `blocked`, overdue todos, bad due dates, unassigned todos (active projects only)
- Changes: status moves, todos done, added, removed, due dates pushed, newly late
- Weekly delivery: a scheduled zap calls `GET /carlos/report` on the webhook and posts the text to Slack

## Dan and Betty: Claude Desktop

`claude_desktop_config.json`, each teammate sets their own name:

```json
{
  "mcpServers": {
    "projects": {
      "command": "uv",
      "args": ["--directory", "D:/projects/fde-takehome", "run", "python", "-m", "projects_kit.mcp_server"],
      "env": { "PROJECTS_USER": "dan" }
    }
  }
}
```

Tools: `list_projects`, `get_project`, `list_todos`, `add_todo`, `complete_todo`, `set_status`. No delete on purpose.
The tools return final wording and the server instructions tell Claude to relay it as is.

## Shared chat (one key for everyone)

`/chat` on the webhook server is a chat page backed by one Claude API key (`ANTHROPIC_API_KEY` in `.env`,
gitignored). Same 6 tools as the MCP server, same model and rules for every user, nothing to install: share the
tunnel URL. Each browser keeps its own conversation; the shared truth is the Projects API.

When a tool runs, the page shows the tool's own text, so the reply format is enforced in code. Claude's own
words appear only when no tool ran (a question back, or "I can't delete").

## Skipped, on purpose

- A custom UI for Betty beyond the chat page: chat covers "nicer than curl" and is one link to share.
- A Slack bot: needs a registered Slack app; the chat page proves the same shared key design.
- A Zapier app: a plain webhook works in all four of Andy's tools.
- LLM written summaries for Carlos: rules are predictable and can't make things up.
- Delete tools for the chatbot: one misread request could lose data.
