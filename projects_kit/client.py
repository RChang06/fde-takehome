"""wrapper over the projects api: fixes its quirks once for every front end."""

import datetime as dt
import difflib
import os
import time

import httpx

BASE = os.environ.get(
    "PROJECTS_API", "https://fde-takehome-projects-api-hkbn2zj27a-ue.a.run.app/api/v1"
)
STATUSES = ["kickoff", "wip", "blocked", "wrapped", "dropped"]
ACTIVE = {"kickoff", "wip", "blocked"}


class KitError(Exception):
    """a failure with the pipeline step, the cause, and one next action."""

    def __init__(self, step, why, next_):
        super().__init__(why)
        self.step, self.why, self.next = step, why, next_

    def render(self, tool):
        return f"✗ {tool} failed at {self.step}\nwhy: {self.why}\nnext: {self.next}"


def _req(method, path, body=None):
    try:
        r = httpx.request(method, BASE + path, json=body, timeout=10)
    except httpx.HTTPError as e:
        raise KitError("API", f"{type(e).__name__} reaching the Projects API",
                       "it may be restarting (data resets); retry in a minute")
    if r.status_code >= 400:
        raise KitError("API", f"upstream {r.status_code} {r.text.strip()[:200]} on {method} {path}",
                       "check the input above; if it looks right, the API changed")
    return r.json()


# reads

def all_projects():
    # the api silently caps pages at 5, so page until we have them all
    out, total = [], None
    while total is None or len(out) < total:
        page = _req("GET", f"/proj?from={len(out)}&take=5")
        total = page["total"]
        if not page["projects"]:
            break
        out += page["projects"]
    return out


def get_project(pid):
    return _req("GET", f"/proj/{pid}")


# dates: the api stores `by` as epoch ms, but accepts any string

def due_ms(by):
    """epoch ms for a stored due value, or None if it is garbage."""
    if isinstance(by, (int, float)):
        return by
    try:
        return dt.datetime.fromisoformat(str(by)).timestamp() * 1000
    except ValueError:
        return None


def parse_due(s):
    """YYYY-MM-DD to epoch ms at the end of that day, local time."""
    try:
        day = dt.date.fromisoformat(s)
    except (TypeError, ValueError):
        raise KitError("VALIDATE", f'due "{s}" is not a date',
                       f"send due as YYYY-MM-DD, e.g. {dt.date.today() + dt.timedelta(days=7)}")
    end = dt.datetime.combine(day, dt.time(23, 59, 59))
    return int(end.timestamp() * 1000)


def fmt_due(by):
    ms = due_ms(by)
    return dt.datetime.fromtimestamp(ms / 1000).strftime("%a %b %d") if ms else f'bad date "{by}"'


def is_late(item, now_ms=None):
    ms = due_ms(item["by"])
    return not item["done"] and ms is not None and ms < (now_ms or time.time() * 1000)


# name resolution: people say "launch", the api wants proj_bc465f

def _pick(query, options, label, where, strict=False):
    """options: list of (name, obj). exact, then substring, else a diagnosis.

    strict: exact name only (case insensitive). for automations, where nobody sees a wrong match."""
    q = query.strip().lower()
    exact = [o for n, o in options if n.lower() == q]
    if len(exact) > 1:
        ids = ", ".join(o["id"] for o in exact)
        raise KitError("RESOLVE", f'{len(exact)} {label}s are named "{query}"{where}',
                       f"names must be unique; rename one, or send the id: {ids}")
    if exact:
        return exact[0]
    hits = [(n, o) for n, o in options if q in n.lower()]
    if len(hits) == 1 and strict:
        raise KitError("RESOLVE", f'no {label} is named exactly "{query}"{where} (strict mode)',
                       f'use the full name: "{hits[0][0]}"')
    if len(hits) == 1:
        return hits[0][1]
    if hits:
        names = ", ".join(f'"{n}"' for n, _ in hits)
        raise KitError("RESOLVE", f'"{query}" matches {len(hits)} {label}s{where}', f"pick one: {names}")
    # typo hint: best word-level similarity, so "lanch" finds "Spring product launch"
    def score(n):
        return max(difflib.SequenceMatcher(None, q, w).ratio() for w in [n.lower(), *n.lower().split()])
    best = max((n for n, _ in options), key=score, default=None)
    hint = (f'closest match is "{best}"' if best and score(best) >= 0.7
            else f"no close {label}; list them first")
    raise KitError("RESOLVE", f'no {label} contains "{query}"{where} (checked {len(options)})', hint)


def find_project(name, strict=False):
    projects = all_projects()
    by_id = [p for p in projects if p["id"] == name]
    return by_id[0] if by_id else _pick(name, [(p["title"], p) for p in projects], "project", "", strict)


def find_todo(project, task, strict=False):
    return _pick(task, [(i["task"], i) for i in project["items"]], "todo", f' in {project["title"]}', strict)


# writes: resolve, validate, do, touch, verify

def _touch(pid):
    # updated_at only moves on touch, so call it after every write
    _req("POST", f"/proj/{pid}/touch", {})


def complete_todo(project, task, done=True, strict=False):
    p = find_project(project, strict)
    item = find_todo(p, task, strict)
    _req("POST", f'/proj/{p["id"]}/items/{item["id"]}/mark', {"flag": "yes" if done else "no"})
    _touch(p["id"])
    after = next((i for i in get_project(p["id"])["items"] if i["id"] == item["id"]), None)
    if not after or after["done"] != done:
        raise KitError("VERIFY", f'API said ok, but {item["id"]} reads back done={after and after["done"]}',
                       "retry once; if it repeats, the API is misbehaving")
    word = "done" if done else "not done"
    return f'✓ Marked "{item["task"]}" {word} in {p["title"]}'


def add_todo(project, task, who, due):
    if not task.strip():
        raise KitError("VALIDATE", "task is empty", "give the todo a short description")
    if not who.strip():
        raise KitError("VALIDATE", "no person given", "assign it to someone, e.g. who=dan")
    by = parse_due(due)
    p = find_project(project)
    # names are our lookup key, so keep them unique per project (the api itself allows duplicates)
    if any(i["task"].lower() == task.strip().lower() for i in p["items"]):
        raise KitError("VALIDATE", f'"{task.strip()}" already exists in {p["title"]}',
                       "use a different name, or mark the existing one done")
    item = _req("POST", f'/proj/{p["id"]}/items/add', {"task": task.strip(), "who": who.strip().lower(), "by": by})
    _touch(p["id"])
    if not any(i["id"] == item["id"] for i in get_project(p["id"])["items"]):
        raise KitError("VERIFY", f'API returned {item["id"]} but it is not in the project',
                       "retry once; if it repeats, the API is misbehaving")
    return f'✓ Added "{item["task"]}" to {p["title"]}\n  who: {item["who"]} · due: {fmt_due(item["by"])}'


def set_status(project, status):
    s = status.strip().lower()
    if s not in STATUSES:
        raise KitError("VALIDATE", f'status "{status}" is not allowed', f"use one of: {', '.join(STATUSES)}")
    p = find_project(project)
    _req("PUT", f'/proj/{p["id"]}/modify', {"status": s})
    _touch(p["id"])
    if get_project(p["id"])["status"] != s:
        raise KitError("VERIFY", f'API said ok, but {p["id"]} status did not change',
                       "retry once; if it repeats, the API is misbehaving")
    return f'✓ {p["title"]}: {p["status"]} → {s}'
