"""dan and betty: talk to projects through claude. the tools are the sandbox; there is no delete.

run (claude desktop config): uv --directory <repo> run python -m projects_kit.mcp_server
"""

import datetime as dt
import os

from mcp.server.mcpserver import MCPServer

from . import client

ME = os.environ.get("PROJECTS_USER", "").lower()

INSTRUCTIONS = f"""You manage a team's projects through these tools only.
- Reply with the tool's result as is. No extra commentary, no summaries on top.
- One tool call per request unless the user asks for more.
- If a result says "pick one", ask the user to pick. Never guess between options.
- Dates: convert words like "Friday" to YYYY-MM-DD yourself. Today is {dt.date.today():%A %Y-%m-%d}.
- "me" means "{ME or 'unknown: ask the user for their name'}".
- You cannot delete projects or todos. If asked, say so."""

mcp = MCPServer("projects", instructions=INSTRUCTIONS)


def _run(tool, fn, *args):
    try:
        return fn(*args)
    except client.KitError as e:
        return e.render(tool)


def _todo_line(p, i):
    mark = "✓" if i["done"] else ("⚠ late" if client.is_late(i) else "·")
    return f'{mark} {i["task"]} ({i["who"] or "unassigned"}, due {client.fmt_due(i["by"])}) [{p["title"]}]'


@mcp.tool()
def list_projects() -> str:
    """All projects with status and open/late todo counts."""
    def go():
        rows = []
        for p in client.all_projects():
            open_ = sum(not i["done"] for i in p["items"])
            late = sum(client.is_late(i) for i in p["items"]) if p["status"] in client.ACTIVE else 0
            rows.append(f'[{p["status"]}] {p["title"]}: {open_}/{len(p["items"])} open' + (f", {late} late" if late else ""))
        return "\n".join(rows)
    return _run("list_projects", go)


@mcp.tool()
def get_project(project: str) -> str:
    """One project's description and every todo. project is a name or part of one."""
    def go():
        p = client.find_project(project)
        head = f'{p["title"]} [{p["status"]}]\n{p["description"]}'
        return "\n".join([head] + [_todo_line(p, i) for i in p["items"]])
    return _run("get_project", go)


@mcp.tool()
def list_todos(person: str = "", late_only: bool = False) -> str:
    """Todos across active projects, optionally for one person and/or only late ones."""
    def go():
        who = ME if person.lower() == "me" else person.lower()
        rows = [_todo_line(p, i) for p in client.all_projects() if p["status"] in client.ACTIVE
                for i in p["items"]
                if (not who or i["who"] == who) and (not late_only or client.is_late(i)) and not i["done"]]
        return "\n".join(rows) or "✓ nothing matches"
    return _run("list_todos", go)


@mcp.tool()
def add_todo(project: str, task: str, due: str, who: str = "me") -> str:
    """Add a todo. due must be YYYY-MM-DD. who defaults to the current user."""
    return _run("add_todo", client.add_todo, project, task, ME if who.lower() == "me" else who, due)


@mcp.tool()
def complete_todo(project: str, task: str, done: bool = True) -> str:
    """Mark a todo done (or not done with done=false). Names can be partial."""
    return _run("complete_todo", client.complete_todo, project, task, done)


@mcp.tool()
def set_status(project: str, status: str) -> str:
    """Set a project's status: kickoff, wip, blocked, wrapped, dropped."""
    return _run("set_status", client.set_status, project, status)


if __name__ == "__main__":
    mcp.run()
