"""carlos: weekly summary. state, what looks stuck, what changed since the last snapshot.

the api keeps no history (updated_at only moves on touch), so we keep our own snapshots.
run: uv run python -m projects_kit.report
"""

import datetime as dt
import json
import pathlib
import time

from . import client

SNAP_DIR = pathlib.Path(__file__).resolve().parent.parent / "snapshots"
ORDER = {s: i for i, s in enumerate(["kickoff", "wip", "wrapped"])}


def save_snapshot(projects):
    SNAP_DIR.mkdir(exist_ok=True)
    now = time.time()
    path = SNAP_DIR / f"{dt.datetime.fromtimestamp(now):%Y-%m-%dT%H-%M-%S}.json"
    path.write_text(json.dumps({"taken_at": now, "projects": projects}))
    return path


def baseline(exclude):
    """the older snapshot closest to 7 days ago, or None on the first run."""
    snaps = []
    for p in sorted(SNAP_DIR.glob("*.json")):
        if p == exclude:
            continue
        try:
            s = json.loads(p.read_text())
            float(s["taken_at"]), list(s["projects"])
            snaps.append(s)
        except (ValueError, KeyError, TypeError):
            pass  # a damaged snapshot is skipped, not fatal
    if not snaps:
        return None
    target = time.time() - 7 * 86400
    return min(snaps, key=lambda s: abs(s["taken_at"] - target))


def stuck_reasons(p, now_ms):
    if p["status"] not in client.ACTIVE:
        return []
    out = ["blocked"] if p["status"] == "blocked" else []
    for i in p["items"]:
        if client.is_late(i, now_ms):
            days = (now_ms - client.due_ms(i["by"])) / 864e5
            out.append(f'late: {i["task"]} ({i["who"] or "unassigned"}, {days:.0f}d)')
        elif client.due_ms(i["by"]) is None:
            out.append(f'bad due date: {i["task"]} ("{i["by"]}")')
        if not i["done"] and not i["who"]:
            out.append(f'unassigned: {i["task"]}')
    return out


def diff(old, new, now_ms):
    """returns (attention, progress) lines comparing two project lists."""
    # match by id; if the api restarted (every id changed), fall back to names, our stable key
    reset = bool(old and new) and not {p["id"] for p in old} & {p["id"] for p in new}
    key = (lambda x, name: x[name].strip().lower()) if reset else (lambda x, name: x["id"])
    old_by_id = {key(p, "title"): p for p in old}
    new_by_id = {key(p, "title"): p for p in new}

    attention = ["the Projects API restarted since then: its data was reset to the seed and due dates regenerated, "
                 "so this compares by name and skips due dates"] if reset else []
    progress = []
    for pid, p in new_by_id.items():
        t = p["title"]
        o = old_by_id.get(pid)
        if not o:
            progress.append(f"new project: {t}")
            continue
        if o["status"] != p["status"]:
            line = f'{t}: {o["status"]} → {p["status"]}'
            forward = ORDER.get(p["status"], -1) > ORDER.get(o["status"], 99)
            (progress if forward else attention).append(line)
        old_items = {key(i, "task"): i for i in o["items"]}
        new_items = {key(i, "task"): i for i in p["items"]}
        done = [i["task"] for k, i in new_items.items() if i["done"] and k in old_items and not old_items[k]["done"]]
        if done:
            progress.append(f"{t}: {len(done)} done ({', '.join(done)})")
        added = [i["task"] for k, i in new_items.items() if k not in old_items]
        if added:
            progress.append(f"{t}: +{len(added)} todo ({', '.join(added)})")
        removed = [i["task"] for k, i in old_items.items() if k not in new_items]
        if removed:
            attention.append(f"{t}: {len(removed)} removed, not done ({', '.join(removed)})")
        reopened = [i["task"] for k, i in new_items.items() if not i["done"] and k in old_items and old_items[k]["done"]]
        if reopened:
            attention.append(f"{t}: {len(reopened)} reopened ({', '.join(reopened)})")
        for k, i in new_items.items():
            if k not in old_items or reset:
                continue  # after a restart the api regenerates every due date, so they can't be compared
            was, now_ = client.due_ms(old_items[k]["by"]), client.due_ms(i["by"])
            if was and now_ and now_ > was and client.fmt_due(now_) != client.fmt_due(was) and not i["done"]:
                attention.append(f'{t}: "{i["task"]}" due pushed {client.fmt_due(was)} → {client.fmt_due(now_)}')
            if client.is_late(i, now_ms) and not client.is_late(old_items[k], o.get("_seen", now_ms)):
                attention.append(f'{t}: newly late, "{i["task"]}" ({i["who"]})')
    for pid, o in old_by_id.items():
        if pid not in new_by_id:
            attention.append(f'project removed: {o["title"]}')
    return attention, progress


def build():
    projects = client.all_projects()
    now_ms = time.time() * 1000
    path = save_snapshot(projects)
    base = baseline(path)

    lines = [f"PROJECTS SUMMARY, {dt.datetime.now():%a %b %d %H:%M}", ""]

    stuck = [(p["title"], r) for p in projects if (r := stuck_reasons(p, now_ms))]
    lines.append("LOOKS STUCK")
    lines += [f"- {t}: {'; '.join(r)}" for t, r in stuck] or ["- nothing"]
    lines.append("")

    if base is None:
        lines += ["CHANGES", "- first run, baseline saved. changes show from the next run."]
    else:
        for p in base["projects"]:
            p["_seen"] = base["taken_at"] * 1000
        attention, progress = diff(base["projects"], projects, now_ms)
        since = dt.datetime.fromtimestamp(base["taken_at"])
        lines.append(f"CHANGES since {since:%a %b %d %H:%M}")
        lines += [f"- needs attention: {x}" for x in attention] + [f"- progress: {x}" for x in progress] or ["- no changes"]
    lines.append("")

    lines.append("ALL PROJECTS")
    for p in sorted(projects, key=lambda p: client.STATUSES.index(p["status"])):
        items = p["items"]
        open_ = sum(not i["done"] for i in items)
        late = sum(client.is_late(i, now_ms) for i in items) if p["status"] in client.ACTIVE else 0
        flag = f", {late} late" if late else ""
        note = " (wrapped but has open todos)" if p["status"] == "wrapped" and open_ else ""
        lines.append(f'- [{p["status"]}] {p["title"]}: {open_}/{len(items)} open{flag}{note}')
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")  # windows consoles default to cp1252
    try:
        print(build())
    except client.KitError as e:
        print(e.render("report"))
