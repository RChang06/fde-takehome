# projects kit

One wrapper (`projects_kit/client.py`) fixes the Projects API's quirks: hidden pages, ids that change on restart, the `flag` yes/no body, unchecked dates. Each person gets a thin front end on top.

```
uv sync
uv run uvicorn projects_kit.webhook:app --port 8000
```

| Who | Use |
|---|---|
| Andy | `POST /andy/complete` `{"project": "...", "task": "..."}`, exact names, JSON or form |
| Carlos | `GET /carlos/report`: state, what looks stuck, what changed since the last snapshot |
| Betty, Dan | `/chat` (one shared API key in `.env`), or `projects_kit/mcp_server.py` in Claude Desktop |

Errors share one shape: the failing step, why, and one next action.

Skipped on purpose: a Zapier app, delete tools, LLM written reports.

# AI Usage

I used Claude Opus 5.5 to help with the design and DeepSeek V4 Flash for implementation.
