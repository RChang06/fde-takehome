"""shared chat: one api key, one model, one set of rules for everyone. same tools as the mcp server.

served by the webhook app at /chat. needs ANTHROPIC_API_KEY in .env (never committed).
"""

import pathlib

import anthropic
from dotenv import load_dotenv
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import mcp_server as tools

load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env")
client = anthropic.Anthropic()
router = APIRouter()
MODEL = "claude-opus-5-5"

FUNCS = {f.__name__: f for f in [tools.list_projects, tools.get_project, tools.list_todos,
                                 tools.add_todo, tools.complete_todo, tools.set_status]}


def _schema(props, required=()):
    return {"type": "object", "properties": props, "required": list(required)}


S = {"type": "string"}
TOOL_DEFS = [
    {"name": "list_projects", "description": tools.list_projects.__doc__, "input_schema": _schema({})},
    {"name": "get_project", "description": tools.get_project.__doc__,
     "input_schema": _schema({"project": S}, ["project"])},
    {"name": "list_todos", "description": tools.list_todos.__doc__,
     "input_schema": _schema({"person": S, "late_only": {"type": "boolean"}})},
    {"name": "add_todo", "description": tools.add_todo.__doc__,
     "input_schema": _schema({"project": S, "task": S, "due": S, "who": S}, ["project", "task", "due", "who"])},
    {"name": "complete_todo", "description": tools.complete_todo.__doc__,
     "input_schema": _schema({"project": S, "task": S, "done": {"type": "boolean"}}, ["project", "task"])},
    {"name": "set_status", "description": tools.set_status.__doc__,
     "input_schema": _schema({"project": S, "status": S}, ["project", "status"])},
]

# per browser history, in memory like the api itself
SESSIONS: dict[str, list] = {}


class Msg(BaseModel):
    session: str
    who: str
    text: str


@router.post("/chat/send")
def send(m: Msg):
    system = tools.INSTRUCTIONS.replace(f'"me" means "{tools.ME or "unknown: ask the user for their name"}"',
                                        f'"me" means "{m.who.strip().lower()}"')
    messages = SESSIONS.setdefault(m.session, [])
    messages.append({"role": "user", "content": m.text})
    outputs = []  # tool results shown verbatim, so the format is enforced in code, not by the prompt
    for _ in range(8):  # cap tool rounds per message
        try:
            r = client.beta.messages.create(
                model=MODEL, max_tokens=16000, system=system, tools=TOOL_DEFS, messages=messages,
                output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            )
        except (anthropic.APIError, TypeError) as e:  # TypeError: no key configured
            messages.pop()
            return {"reply": f"✗ chat failed at MODEL\nwhy: {type(e).__name__}: {e}\nnext: check the API key in .env, then retry"}
        messages.append({"role": "assistant", "content": r.content})
        if r.stop_reason == "refusal":
            return {"reply": "✗ chat failed at MODEL\nwhy: the model declined this request\nnext: rephrase it"}
        if r.stop_reason != "tool_use":
            text = "\n".join(b.text for b in r.content if b.type == "text").strip()
            return {"reply": "\n\n".join(outputs) or text}
        results = []
        for b in r.content:
            if b.type == "tool_use":
                out = FUNCS[b.name](**b.input) if b.name in FUNCS else f"✗ unknown tool {b.name}"
                outputs.append(out)
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": out,
                                "is_error": out.startswith("✗")})
        messages.append({"role": "user", "content": results})
    return {"reply": "✗ chat failed at MODEL\nwhy: too many tool rounds for one message\nnext: split the request"}


@router.get("/chat", response_class=HTMLResponse)
def page():
    return PAGE


PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Projects chat</title><style>
body{font:15px system-ui;max-width:720px;margin:0 auto;padding:16px;background:#fafafa;color:#222}
#log{white-space:pre-wrap}.u{margin:12px 0 4px;font-weight:600}.a{background:#fff;border:1px solid #ddd;border-radius:8px;padding:10px}
form{display:flex;gap:8px;margin-top:16px}input{flex:1;padding:10px;font:inherit}button{padding:10px 16px}
@media(prefers-color-scheme:dark){body{background:#151515;color:#eee}.a{background:#222;border-color:#333}}
</style></head><body><h2>Projects</h2><div id="log"></div>
<form id="f"><input id="t" placeholder="e.g. what's late?" autofocus><button>Send</button></form>
<script>
let who=localStorage.who||prompt("Your name (andy, betty, carlos, dan)?")||"";localStorage.who=who;
let s=localStorage.s||(localStorage.s=crypto.randomUUID());
const log=document.getElementById("log"),t=document.getElementById("t");
function add(c,x){const d=document.createElement("div");d.className=c;d.textContent=x;log.append(d);scrollTo(0,1e9)}
document.getElementById("f").onsubmit=async e=>{e.preventDefault();const x=t.value.trim();if(!x)return;t.value="";
add("u",x);add("a","…");const r=await fetch("/chat/send",{method:"POST",headers:{"content-type":"application/json"},
body:JSON.stringify({session:s,who,text:x})});log.lastChild.textContent=(await r.json()).reply}
</script></body></html>"""
