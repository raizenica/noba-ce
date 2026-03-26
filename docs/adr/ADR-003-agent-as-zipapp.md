# ADR-003: Agent Distributed as Python Zipapp (`.pyz`)

**Status:** Accepted
**Date:** 2026-02-01
**Deciders:** Raizen

---

## Context

The NOBA agent must run on managed Linux hosts — including containers and minimal VMs — where the operator may not be able to install packages from PyPI. The agent ships several internal modules (`metrics.py`, `commands.py`, `rdp.py`, `terminal.py`, `healing.py`, `websocket.py`) that must travel together.

Distribution options considered:
1. **Single `agent.py` file** — ship one monolithic script. Simple, but grows unwieldy as features accumulate; cross-module imports require runtime path hacking.
2. **Install via pip** — `pip install noba-agent`. Requires PyPI access and a writable environment; breaks on hosts where pip is locked or absent.
3. **Compiled binary (PyInstaller / Nuitka)** — truly self-contained, but requires a build VM per target arch, adds a large compile step to CI, and makes the source opaque.
4. **Python zipapp (`.pyz`)** — bundle the package directory into a single zip file that Python's import machinery can execute directly.

## Decision

Build `noba-agent.pyz` using Python's built-in `zipapp` module:

```bash
# scripts/build-agent.sh
python3 -m zipapp share/noba-agent \
    --python "/usr/bin/env python3" \
    --output share/noba-agent/agent.pyz \
    --main __main__:main
```

The `share/noba-agent/` directory is the package root. `__main__.py` serves as the entry point and imports sibling modules normally (`from metrics import collect_metrics`). The resulting `.pyz` is:
- A standard zip file (inspectable with `unzip -l`)
- Executable: `python3 agent.pyz --server http://noba:8080 --key KEY`
- Self-updating: the server serves the current `.pyz` at `/api/agent/update`; the agent downloads and replaces itself atomically

The server auto-update endpoint compares a SHA-256 digest so agents only download when the content changes.

## Consequences

**Positive:**
- Zero external dependencies at runtime — all internal modules bundled
- One file to deploy, copy, or `curl` to a target host
- Standard Python tooling (no PyInstaller quirks, no binary blobs)
- Source remains readable — `unzip -p agent.pyz metrics.py` shows the module
- Atomic self-update: write to `.pyz.tmp`, `os.replace()` — no partial state

**Negative:**
- Third-party packages (`psutil`, `pyyaml`) cannot be bundled this way — they are optional dependencies detected at runtime with `try: import psutil`
- The `__main__.py` bootstrap must be careful about import order (version constant set before submodule imports)
- `.pyz` cannot be directly debugged with `python3 -m pdb` without extraction

**Why not single file:**
The agent had grown to 6 modules by the time this decision was made. Merging them back into one file would have made the codebase significantly harder to navigate and test in isolation.
