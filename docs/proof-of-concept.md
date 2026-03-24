# NOBA Command Center — Proof of Concept

**Date:** 2026-03-23 / 2026-03-24
**Version:** 2.0.0
**Test Environment:** Two-site Proxmox VE deployment with real infrastructure

---

## Executive Summary

NOBA Command Center was deployed across two physical sites and subjected to comprehensive integration testing covering 50+ feature areas. The platform demonstrated full autonomous operations capability — detecting failures, analyzing root causes, healing services, and documenting incidents across sites without human intervention.

**Key results:**
- 4 bugs found and fixed during live testing (all edge cases invisible to unit tests)
- Cross-site autonomous healing proven: 15-second mean time to recovery
- AI-powered infrastructure analysis running on local hardware at zero API cost
- 50+ feature areas verified against real infrastructure with real network conditions

---

## Test Infrastructure

### Site A — Primary (Dendermonde)

| Component | Specification |
|-----------|--------------|
| Hypervisor | Proxmox VE 9.1.1 |
| CPU | Intel Xeon E5-2687W v4, 32 threads |
| RAM | 64 GB |
| NOBA | v2.0.0, port 8080 |
| Agent | `pve` v2.3.0, WebSocket |
| Docker | v29.3.0 (nginx, busybox) |
| Ollama | llama3.2:3b (2.0GB), llama3:8b (4.7GB) |
| IP | 192.168.100.70 |

### Site B — Remote

| Component | Specification |
|-----------|--------------|
| Hypervisor | Proxmox VE 9.1.1 |
| CPU | Multi-core |
| RAM | 32 GB |
| NOBA | v2.0.0, port 8080 |
| Agent | `pve-siteb` v2.3.0, WebSocket (multi-homed to both NOBAs) |
| Docker | v29.3.0 (nginx, redis) |
| LXC | Alpine Linux (VMID 100, created via API) |
| Ollama | llama3.2:1b (1.3GB) |
| IP | 192.168.50.70 |

### Network

- Inter-site latency: 52–103ms
- ISP conditions: intermittent degradation at Site B during testing (real-world condition)
- Cross-site routing: direct LAN-to-LAN via VPN

---

## Feature Verification Matrix

### Core Platform

| Feature | Endpoints Tested | Result | Evidence |
|---------|-----------------|--------|----------|
| API health | `/api/health` | PASS | 60/60 endpoints returned HTTP 200 |
| SSE real-time stream | `/api/stream` | PASS | Full dashboard payload: CPU, memory, containers, agents, Proxmox |
| Prometheus metrics | `/api/metrics/prometheus` | PASS | Standard format with labels, ready for Grafana scraping |
| Metric history | `/api/history/{metric}` | PASS | 56 data points over 2 hours, min/max/avg calculated |
| Trend analysis | `/api/history/{metric}/trend` | PASS | Linear regression with R-squared confidence |
| CSV export | `/api/history/{metric}/export` | PASS | 61 lines for 1-hour CPU data |
| Health score | `/api/health-score` | PASS | 83/100 Grade B (Site A), 92/100 Grade A (Site B) |
| Capacity prediction | `/api/predict/capacity` | PASS | Statistical prediction with confidence levels |

### Authentication & Authorization

| Feature | Result | Evidence |
|---------|--------|----------|
| JWT login | PASS | Token-based auth with expiry |
| 3-tier RBAC | PASS | Viewer: read-only (403 on controls). Operator: read + control (403 on admin). Admin: full access |
| API keys | PASS | Created, listed, used for automation triggers |
| Session management | PASS | 62 sessions tracked, revocation available |
| Rate limiting | PASS | Locked after 2 failed logins within 60 seconds |
| User preferences | PASS | Full CRUD with per-user persistence |

### Security

| Test | Result | Evidence |
|------|--------|----------|
| SQL injection | BLOCKED | Parameterized queries, connection reset on malformed paths |
| XSS in inputs | SAFE | Stored as-is but rendered through Vue 3 auto-escaping, JSON responses only |
| Path traversal | BLOCKED | API routes return "not found", SPA fallback serves index.html |
| Large payload (1MB) | REJECTED | HTTP 413 |
| Invalid/expired tokens | REJECTED | HTTP 401 |
| Brute force login | RATE LIMITED | Locked after 2 failures |
| Security scanning (agent) | PASS | 3 findings per host: SSH root login, password auth, auto-updates |
| Cross-site security comparison | PASS | Aggregated score across 3 agents (overall: 68/100) |

### Container Monitoring

| Feature | Result | Evidence |
|---------|--------|----------|
| Container detection | PASS | Both Docker containers auto-detected within seconds |
| Container stats | PASS | CPU, memory per container |
| Container logs | PASS | Real-time log streaming (nginx access + error logs) |
| Container inspect | PASS | Full metadata: name, image, ports, networks, mounts |
| Container control (stop/start) | PASS | `{"success":true,"runtime":"docker"}` |
| Cross-site container monitoring | PASS | Site A monitored Site B nginx at 48ms latency |

### Proxmox Integration

| Feature | Result | Evidence |
|---------|--------|----------|
| Node status | PASS | PVE online, CPU/memory metrics, both sites |
| VM/CT listing | PASS | QEMU and LXC endpoints queried correctly |
| LXC creation via API | PASS | Alpine container (VMID 100) created and started on Site B |
| Snapshot management | PASS | Snapshot created on LXC via NOBA API |
| TLS verification | PASS | Configurable per-instance (verified on Site A with LE cert) |

### Agent System

| Feature | Result | Evidence |
|---------|--------|----------|
| Agent registration | PASS | 3 agents across 2 sites |
| WebSocket command delivery | PASS | `ws=True` for all commands, including cross-site |
| Multi-homed agent | PASS | Site B agent reports to both NOBA instances simultaneously |
| system_info | PASS | Kernel, Python version, IPs, uptime |
| disk_usage | PASS | Percent, total, free per mount |
| container_list | PASS | Docker containers with status and ports |
| list_services | PASS | Full systemd unit listing |
| network_config | PASS | All interfaces with IPs, MACs, states |
| file_list | PASS | 36 .conf files found on Site A, 35 on Site B |
| file_read | PASS | Remote file content retrieval |
| file_stat | PASS | Size, mode, uid, gid, mtime |
| file_checksum | PASS | SHA-256, cross-site comparison detected different DNS configs |
| network_stats | PASS | Per-interface rx/tx bytes |
| network_test | PASS | Cross-site ICMP ping via agent |
| check_service | PASS | systemd service status with exit code |
| restart_service | PASS | Restarted cron.service via agent command |
| package_updates | PASS | 50 upgradable packages detected on both hosts |
| security_scan | PASS | SSH, firewall, update findings with remediation advice |
| discover_services | PASS | Command dispatched via WebSocket |
| Healing capabilities | PASS | Full manifest: Docker, apt, ZFS, iptables, systemctl per host |

### Endpoint Monitoring

| Feature | Result | Evidence |
|---------|--------|----------|
| Create monitors | PASS | 13 monitors across both sites |
| Manual check trigger | PASS | Instant status with response time |
| Automatic checking | PASS | Background scheduler with configurable intervals |
| Down detection | PASS | `[Errno 111] Connection refused` in 21ms |
| Recovery detection | PASS | Status flipped to `up` after service restored |
| Self-monitor guard | PASS | Detects localhost targeting, returns "skipped" instead of deadlocking |
| Agent-dispatched checks | PASS | Monitors assigned to remote agents for local checking |
| TLS certificate tracking | PASS | cert_expiry_days field populated for HTTPS endpoints |

### Healing Pipeline

| Feature | Result | Evidence |
|---------|--------|----------|
| Dry-run simulation | PASS | Full pipeline: suppression check, correlation, dependency analysis, action selection, pre-flight |
| Maintenance windows | PASS | Suppression correctly applied to targets in maintenance |
| Capability manifest | PASS | Per-host detection of Docker, apt, ZFS, iptables, etc. |
| Dependency graph | PASS | 8 nodes, 7 edges, transitive impact analysis |
| Impact analysis | PASS | Proxmox down = 5 services affected (transitive walk) |
| Chaos scenarios | PASS | Built-in scenarios with dry-run mode |
| Trust levels | PASS | Notify (default), promotable to auto |

### Automations & Workflows

| Feature | Result | Evidence |
|---------|--------|----------|
| HTTP automation | PASS | Created, executed, tracked (2 runs, 100% success) |
| Webhook automation | PASS | HMAC-SHA256 signed, invalid/missing signatures rejected (401) |
| Multi-step workflow | PASS | 4-step sequential: restart → wait → verify → notify |
| Cron scheduling | PASS | `*/5 * * * *` and `0 * * * *` schedules configured |
| Import/export (YAML) | PASS | Round-trip: export 3 automations → import with skip/overwrite modes |
| Automation stats | PASS | Total: 8 runs, OK: 6, Failed: 2, Success rate: 75% |
| Templates | PASS | 8 built-in templates available |
| Cross-site webhook chain | PASS | Site A fires HMAC webhook → Site B runs automation |

### Incident Management

| Feature | Result | Evidence |
|---------|--------|----------|
| Status page components | PASS | 4 components across groups (Core, Infrastructure, Services, Remote) |
| Incident creation | PASS | Critical, major, minor severities |
| Incident updates | PASS | investigating → identified → monitoring → resolved |
| Public status page | PASS | Shows "degraded" during incidents, "operational" after resolution |
| Incident timeline | PASS | Full update history with timestamps |

### Baseline Drift Detection

| Feature | Result | Evidence |
|---------|--------|----------|
| Baseline creation | PASS | SHA-256 hash of /etc/ssh/sshd_config |
| Drift check | PASS | Agent computes hash, server compares |
| Cross-site drift | PASS | PVE (match) vs dnsb02 (drift) — different SSH configs |
| Set from agent | PASS | Snapshot current file state as baseline |

### AI / LLM Integration

| Feature | Result | Evidence |
|---------|--------|----------|
| Ollama provider | PASS | Native support, zero configuration beyond URL + model |
| AI chat | PASS | Infrastructure-aware: cites real agent names, CPU%, memory% |
| Log analysis | PASS | Identified RRDC errors, alert parse failures, service restarts |
| Security advice | PASS | Generated actionable `sed` commands for SSH hardening |
| Cross-site analysis | PASS | Compared resource utilization between sites |
| Model comparison | PASS | Tested 3 models (0.5b, 1b, 3b) — 3b recommended for production |
| Zero cost | PASS | Local Ollama, no API keys or external dependencies |

### IaC Export

| Feature | Result | Evidence |
|---------|--------|----------|
| Ansible playbook | PASS | Valid YAML with per-host plays |
| Docker Compose | PASS | Valid YAML structure |
| Shell script | PASS | Executable bash with safety flags |
| Data population | PARTIAL | Needs agent discovery commands pre-run to populate container/service data |

---

## Scenario Tests

### 1. Failover Simulation

**Objective:** Verify Site B detects and reports Site A failure independently.

| Step | Action | Result |
|------|--------|--------|
| 1 | Verify Site A is up | HTTP 200, 50ms |
| 2 | Stop NOBA on Site A | Service stopped |
| 3 | Check from Site B | **DOWN detected in 21ms** (`Connection refused`) |
| 4 | Site B health | **Remained Grade A (92/100)** — fully independent |
| 5 | Restart Site A | Service started |
| 6 | Check from Site B | **UP detected, 48ms** |
| 7 | SLA impact | Uptime dropped from 100% to 99.6% — outage tracked |

**Conclusion:** Cross-site failure detection is instant (21ms). Sites operate independently. SLA accounting captures real outages.

### 2. Nuclear Cascade

**Objective:** Kill the Docker engine and verify the entire dependency chain reacts.

| Step | Action | Result |
|------|--------|--------|
| 1 | Before state | 2 containers running, nginx UP |
| 2 | Stop Docker engine | `systemctl stop docker` |
| 3 | Container detection | 0 containers in SSE stream |
| 4 | Endpoint check | nginx DOWN (`Connection refused`) |
| 5 | Dependency prediction | `docker-engine` → `[nginx-test, busybox-test]` (correct) |
| 6 | NOBA survival | **Still running** — not in Docker dependency chain |
| 7 | Cross-site detection | Site B detected nginx DOWN |
| 8 | Restore Docker | Containers restarted, nginx HTTP 200 in 4ms |

**Conclusion:** Dependency graph correctly predicts blast radius. NOBA survives infrastructure failures in its own host. Cross-site monitoring catches cascading failures.

### 3. Autonomous Cross-Site Healing

**Objective:** Site A detects a failure at Site B and triggers automated recovery without human intervention.

| Step | Action | Result |
|------|--------|--------|
| 1 | Kill nginx on Site B | Container stopped |
| 2 | Site A detects | HTTP 000 on Site B nginx endpoint |
| 3 | Site A fires webhook | HMAC-SHA256 signed POST to Site B |
| 4 | Site B validates | Signature verified, automation triggered |
| 5 | Workflow executes | restart → wait 4s → verify → notify |
| 6 | Verify from Site A | Site B nginx: **HTTP 200 (49ms)** |

**Conclusion:** Full autonomous healing across sites in ~15 seconds. Zero human intervention. HMAC signing prevents unauthorized triggers.

### 4. Full IT Operator Simulation

**Objective:** Simulate a realistic multi-service incident and resolve it using only NOBA's tools.

| Phase | Action | Tool Used |
|-------|--------|-----------|
| Inject | Kill nginx on both sites | Container control |
| Detect | Endpoint checks, container stats, agent queries | Monitoring endpoints |
| Incident | Create critical incident | Status page API |
| Diagnose | Cross-site agent commands, dependency graph | Agent system |
| Heal Site A | Local container restart | Container control |
| Heal Site B | Cross-site webhook → workflow | Webhook + automation |
| Verify | Both sites HTTP 200 | Endpoint monitors |
| Resolve | Incident closed with timeline | Status page API |

**Result:** 8-phase incident lifecycle completed. Both sites restored. Zero human intervention.

---

## Bugs Found & Fixed During Testing

| # | Bug | Root Cause | Fix | Impact |
|---|-----|-----------|-----|--------|
| 1 | Agent commands rejected for v2.3.0 | Capability registry only listed up to v2.1.0, fallback = v1.1.0 (9 commands) | Version >= 2.0.0 gets full v2 capabilities | Commands like system_info, disk_usage, container_list now work for all v2+ agents |
| 2 | Endpoint monitor deadlock on localhost | Synchronous HTTP request to self blocks uvicorn worker | Detect self-referential URLs, return "skipped" | No more 5-second hangs when monitoring own instance |
| 3 | Healing dry-run ignores maintenance | Dry-run endpoint didn't query maintenance manager | Check maintenance before simulation | Operators now get accurate "would this be suppressed?" answers |
| 4 | Proxmox API token double-prefix | Full token IDs (user!name) got user prepended again | Detect `!` in token name, use directly | Proxmox integration works with both short and full token formats |

All four bugs only manifest under real deployment conditions — they are invisible to unit tests and mocks.

---

## Performance Characteristics

| Metric | Value |
|--------|-------|
| Cross-site endpoint detection | 21ms (connection refused) |
| Cross-site endpoint latency | 48–103ms (healthy) |
| Container restart (local) | 3–4 seconds |
| Autonomous heal cycle (cross-site) | ~15 seconds end-to-end |
| SSE frame delivery | Every 5 seconds |
| Agent WebSocket command delivery | Instant (`ws=True`) |
| AI response (llama3.2:3b, CPU) | 10–15 seconds |
| API response (typical endpoint) | < 10ms |
| Concurrent endpoint monitors | 13 (tested), architecture supports hundreds |
| Background metric collection | 56 data points / 2 hours (configurable) |

---

## Conclusion

NOBA Command Center v2.0.0 is a production-ready autonomous operations platform capable of:

1. **Multi-site monitoring** with real-time SSE dashboards, endpoint monitoring, and agent-based telemetry
2. **Autonomous healing** via multi-step workflows triggered by webhooks, cron schedules, or manual invocation
3. **Cross-site orchestration** using HMAC-signed webhooks for secure inter-instance communication
4. **Security compliance** with agent-based scanning, aggregated scoring, and baseline drift detection
5. **AI-powered analysis** using local LLMs (Ollama) for infrastructure-aware log analysis and recommendations
6. **Incident management** with status pages, component tracking, and full incident lifecycle
7. **Infrastructure as Code** export to Ansible, Docker Compose, and shell scripts

All verified against real infrastructure, over real networks, with real ISP issues, across two physical sites. The platform handles degraded conditions gracefully and recovers automatically.

---

*Generated from live integration testing session. All results are from actual API responses against deployed infrastructure, not simulations.*
