"""andy: one webhook his zapier/n8n/make/gumloop step can call. names in, no ids.

run: uv run uvicorn projects_kit.webhook:app --port 8000
public url for zapier: cloudflared tunnel --url http://localhost:8000
"""

import json
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from . import chat, client, report

app = FastAPI(title="projects kit")
app.include_router(chat.router)  # /chat for betty and teammates
CODES = {"RESOLVE": 404, "VALIDATE": 422, "API": 502, "VERIFY": 502}


def _fields(raw):
    # zapier defaults to form data, others send json with or without the header, so accept both
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    return {k: v[0] for k, v in parse_qs(raw).items()}


BODY_DOC = {"requestBody": {"content": {"application/json": {"schema": {
    "type": "object", "required": ["project", "task"],
    "properties": {"project": {"type": "string", "example": "Spring product launch"},
                   "task": {"type": "string", "example": "Finalize launch blog post"},
                   "done": {"type": "boolean", "default": True}}}}}}}


@app.post("/andy/complete", response_class=PlainTextResponse, openapi_extra=BODY_DOC)
async def complete(request: Request):
    try:
        f = _fields((await request.body()).decode("utf-8", "replace"))
        project, task = str(f.get("project", "")).strip(), str(f.get("task", "")).strip()
        done = str(f.get("done", True)).strip().lower() not in ("false", "0", "no")
        if not project or not task:
            raise client.KitError("VALIDATE", "project and task are both required",
                                  'send {"project": "Spring product launch", "task": "Finalize launch blog post"}')
        # strict: an unattended automation should act on exact names only
        return client.complete_todo(project, task, done, strict=True)
    except client.KitError as e:
        # non-2xx so the automation tool marks the step as failed
        return PlainTextResponse(e.render("complete"), status_code=CODES[e.step])


@app.get("/carlos/report", response_class=PlainTextResponse)
def weekly_report():
    # lets a scheduled zap pull the summary and post it to slack
    try:
        return report.build()
    except client.KitError as e:
        return PlainTextResponse(e.render("report"), status_code=CODES[e.step])
