---
name: deploy
description: Deploy current NOBA code to local production - runs lint gates, frontend build, install.sh, service restart, health check, and journal verification
disable-model-invocation: true
---

# Deploy NOBA to Production

Run these steps sequentially. Stop and report on first failure.

## Step 1: Lint Gate (Python)

```bash
ruff check share/noba-web/server/
```

If ruff reports errors, fix them before continuing.

## Step 2: Frontend Tests

```bash
cd share/noba-web/frontend && npx vitest run
```

If any tests fail, fix them before continuing.

## Step 3: Frontend Build

```bash
cd share/noba-web/frontend && npm ci --silent && npm run build
```

Verify `share/noba-web/static/dist/index.html` exists after build.

## Step 4: Shell Syntax Gate

Run `bash -n` on all shell scripts:

```bash
for f in libexec/*.sh install.sh; do bash -n "$f" || exit 1; done
```

## Step 5: Install

```bash
bash install.sh -y --skip-deps
```

## Step 6: Restart Service

```bash
systemctl --user daemon-reload
systemctl --user restart noba-web.service
```

Wait 3 seconds for startup.

## Step 7: Health Check

```bash
curl -sf http://localhost:8080/api/health
```

Must return HTTP 200 with valid JSON.

## Step 8: Journal Check

```bash
journalctl --user -u noba-web.service --since "30 seconds ago" --no-pager
```

Scan output for `ERROR`, `Traceback`, or `CRITICAL`. Report any issues found.

## Step 9: Report

Summarize: which gates passed, build result, install result, service status, health response, and any journal warnings.
