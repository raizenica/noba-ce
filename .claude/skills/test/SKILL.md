---
name: test
description: Run the full NOBA test suite - pytest backend tests, vitest frontend tests, shell syntax validation, Python linting, and optionally e2e tests via dev harness
disable-model-invocation: true
---

# Run NOBA Test Suite

Run these steps sequentially. Report results for each stage.

## Step 1: Python Tests

```bash
pytest tests/ -v
```

Report pass/fail counts.

## Step 2: Frontend Tests

```bash
cd share/noba-web/frontend && npx vitest run
```

Report pass/fail counts.

## Step 3: Python Lint

```bash
ruff check share/noba-web/server/
```

## Step 4: Shell Syntax Validation

```bash
for f in libexec/*.sh install.sh; do
  [ -f "$f" ] && bash -n "$f"
done
```

Report any syntax errors.

## Step 5: E2E Tests (optional)

Only run if the user explicitly requests e2e or full tests. Requires NOBA_DEV_PASS.

```bash
bash dev/harness.sh start
python3 dev/e2e.py --port 8099 --host 127.0.0.1 --password "$NOBA_DEV_PASS"
bash dev/harness.sh stop
```

## Step 6: Report

Summarize all stages with pass/fail status. If any stage failed, list the specific failures.
