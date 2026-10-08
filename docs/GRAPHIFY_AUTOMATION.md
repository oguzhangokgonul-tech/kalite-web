# Local Code Graph Automation

The Windows development workspace has a VS Code folder-open task named
`Graphify: Watch code`. Allow automatic tasks for this trusted workspace when
VS Code asks. It runs `scripts/watch-graphify.ps1`; a project-specific mutex
prevents duplicate watchers. Nothing is installed on the production server.

The watcher waits eight seconds after saves, then updates `graph.json`,
`graph.html` and `GRAPH_REPORT.md` using local AST analysis and at most two
extraction workers. Refresh an already-open browser tab to see new output.
No LLM or API key is used. Documents/images only produce a pending-update
notice; they are not automatically sent to an external service.

Prerequisites: the existing `uv tool` Graphify installation and `watchdog` in
its Python environment. Alternatively, set `GRAPHIFY_PYTHON` to that interpreter.
The script checks dependencies and does not install anything silently.

```powershell
# Start manually when the IDE task is unavailable; Ctrl+C stops the watcher.
powershell -NoProfile -File scripts/watch-graphify.ps1

# One-time refresh without a running watcher.
graphify update .

# The optional tree is a snapshot, not an automatically updated output.
graphify tree --root . --label VolkaPortal
```

`.graphifyignore` excludes customer data, backups, credentials, runtime and
temporary files. `.gitignore` excludes generated graph artifacts. The graph
describes the working tree (including uncommitted code), not only HEAD.
