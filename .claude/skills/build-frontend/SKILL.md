---
name: build-frontend
description: Build the Vue 3 frontend with Vite - installs dependencies, runs vitest, builds production bundle, and reports output sizes
disable-model-invocation: true
---

# Build NOBA Frontend

Run these steps sequentially. Stop and report on first failure.

## Step 1: Install Dependencies

```bash
cd share/noba-web/frontend && npm ci --silent
```

## Step 2: Run Frontend Tests

```bash
cd share/noba-web/frontend && npx vitest run
```

Report pass/fail counts. Stop if any tests fail.

## Step 3: Build Production Bundle

```bash
cd share/noba-web/frontend && npm run build
```

## Step 4: Verify Output

Check that `share/noba-web/static/dist/index.html` exists.

Report bundle sizes:

```bash
du -sh share/noba-web/static/dist/
find share/noba-web/static/dist/assets -type f -name '*.js' -o -name '*.css' | xargs ls -lh
```

## Step 5: Report

Summarize: dependency install status, test results, build status, and output sizes.
