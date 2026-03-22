# Full Self-Healing Platform Design

**Date:** 2026-03-22
**Status:** Draft
**Predecessor:** `docs/superpowers/specs/2026-03-22-self-healing-pipeline-design.md` (pipeline infrastructure — already implemented)

## Overview

Evolve NOBA from a monitoring platform with basic self-healing into a **fully autonomous self-healing infrastructure platform**. The pipeline infrastructure (correlation, planner, executor, ledger, governor, agent runtime) already exists. This spec covers everything needed to make it truly comprehensive:

1. **55+ cross-platform heal actions** with capability-based dispatch (not OS-based)
2. **Universal integration layer** — abstract operations mapped to 24+ platform categories
3. **Dependency graph with root cause analysis** — heal upward, suppress downward
4. **Agent-verified healing** — never blindly heal what you can't reach
5. **Tiered approval model** — adaptive to user base, with escalation and emergency override
6. **Predictive/proactive healing** — prediction engine + anomaly detection wired to pipeline
7. **Maintenance windows** — per-target + global, scheduled + ad-hoc
8. **Rollback with state snapshots** — undo heals that make things worse
9. **Internal resilience** — subsystems monitor each other, graceful degradation
10. **Chaos testing framework** — intentional fault injection with dry-run mode
11. **Full healing dashboard UI** — 10 panels covering effectiveness, dependencies, approvals, analytics
12. **Enriched notifications** — full evidence context, dedicated heal channel, digest mode

### Design Principles

- **Never trust labels** — verify capabilities before acting
- **Never heal blind** — if you can't verify the target is actually down, don't restart it
- **Heal upward, suppress downward** — find the root cause in the dependency graph
- **Fail safe** — if anything is uncertain, notify instead of act
- **Everything configurable** — every timeout, threshold, window, and behavior is YAML-configurable
- **Everything audited** — every action, approval, rollback, and suppression is recorded
- **Platform-agnostic** — abstract operations, not hardcoded integrations

---

## Section 1: Capability-Based Action Dispatch

### Why Not OS Detection

Trusting `os: "linux"` is a design flaw. Linux can mean Debian (apt), Fedora (dnf), Alpine (apk, no systemd), or a container. Windows can mean Server 2022 with PowerShell 7 or an old box without it. WSL reports as Linux inside Windows.

### Agent Capability Manifest

The agent reports a capability manifest on startup, refreshed every 6 hours, and on-demand after capability mismatches or package changes.

```python
{
    "os": "linux",
    "distro": "ubuntu",
    "distro_version": "24.04",
    "kernel": "6.8.0",
    "init_system": "systemd",          # systemd | openrc | runit | launchd | windows_scm
    "is_wsl": false,
    "is_container": false,
    "capabilities": {
        "docker": {"available": true, "version": "27.1", "socket": "/var/run/docker.sock"},
        "podman": {"available": false},
        "systemctl": {"available": true},
        "apt": {"available": true},
        "dnf": {"available": false},
        "apk": {"available": false},
        "certbot": {"available": true, "path": "/usr/bin/certbot"},
        "zfs": {"available": true, "pools": ["rpool", "tank"]},
        "btrfs": {"available": false},
        "tailscale": {"available": true, "version": "1.62"},
        "iptables": {"available": false},
        "nftables": {"available": true},
        "logrotate": {"available": true},
        "powershell": {"available": false},
        "wevtutil": {"available": false},
        "ip": {"available": true},
        "ifconfig": {"available": false},
    }
}
```

### Capability States

```
available   -> tool exists and works (verified by pre-flight)
degraded    -> tool exists but last pre-flight failed
unavailable -> tool not found
unknown     -> never probed (fresh agent)
```

### Capability Refresh Triggers

- Agent startup
- Every 6 hours (configurable)
- After `package_install` / `package_remove` actions
- After a "capability mismatch" error (immediate re-probe)
- On-demand via `refresh_capabilities` command from server

### Action Dispatch with Fallback Chains

Each action has ordered handlers that match against capabilities. First matching handler wins. No match = abort + notify.

```python
"service_restart": {
    "handlers": [
        {"requires": "systemctl", "cmd": "systemctl restart {service}"},
        {"requires": "rc-service", "cmd": "rc-service {service} restart"},
        {"requires": "service",    "cmd": "service {service} restart"},
        {"requires": "powershell", "cmd": "Restart-Service {service}"},
    ],
}

"package_security_patch": {
    "handlers": [
        {"requires": "apt",    "cmd": "apt upgrade -y --security"},
        {"requires": "dnf",    "cmd": "dnf upgrade --security -y"},
        {"requires": "apk",    "cmd": "apk upgrade"},
        {"requires": "powershell", "cmd": "Install-WindowsUpdate -AcceptAll -SecurityOnly"},
    ],
}

"network_interface_restart": {
    "handlers": [
        {"requires": "ip",       "cmd": "ip link set {nic} down && ip link set {nic} up"},
        {"requires": "ifconfig", "cmd": "ifconfig {nic} down && ifconfig {nic} up"},
        {"requires": "powershell", "cmd": "Restart-NetAdapter -Name '{nic}'"},
    ],
}
```

### Pre-Flight Checks (Every Action, Every Time)

Before executing ANY heal action:

1. **Tool exists** — specific binary/command available (from manifest)
2. **Permissions** — agent has required privileges (sudo, admin)
3. **Target exists** — container/service/file actually exists right now
4. **Not in maintenance** — target isn't in a maintenance window
5. **Dependencies OK** — don't heal if root cause is upstream
6. **Platform compatible** — action has a handler for this capability set

If ANY pre-flight fails: abort, don't guess, notify operator with exactly what failed and why.

### Manifest Verification

Even if manifest says `docker: available`, pre-flight verifies `docker ps` actually works before trying `docker restart`. If it fails, capability downgraded to `degraded`, operator notified.

---

## Section 2: Cross-Platform Action Registry

### Action Entry Schema

Every action in the registry includes:

```python
{
    "risk": "low|medium|high",
    "timeout_s": int,
    "settle_s": int,
    "reversible": bool,
    "reverse_action": str | None,
    "platforms": ["linux", "windows"],  # or ["any"] for API-based
    "health_check": callable | None,
    "snapshot_fields": [...],           # state to capture before execution
}
```

### Low-Risk Actions (fully automated, agent-eligible)

| Action | Linux | Windows | Description |
|--------|-------|---------|-------------|
| `service_restart` | `systemctl restart` | `Restart-Service` | Existing |
| `service_reload` | `systemctl reload` | `Restart-Service` (no reload) | Config reload |
| `service_reset_failed` | `systemctl reset-failed` | `sc.exe failure reset` | Clear failure state |
| `restart_container` | `docker restart` | `docker restart` | Existing |
| `container_pause` | `docker pause/unpause` | `docker pause/unpause` | Resource relief |
| `container_image_pull` | `docker pull` | `docker pull` | Pull latest, no restart |
| `process_kill` | `kill -TERM/-KILL` | `Stop-Process -Force` | Kill runaway processes |
| `nice_adjust` | `renice` / `ionice` | `Get-Process \| Set-Priority` | Deprioritize before killing |
| `log_rotate` | `logrotate -f` | `Clear-Content` + archive | Force log rotation |
| `temp_cleanup` | `find /tmp -mtime +N -delete` | `Remove-Item $env:TEMP` | Purge old temp files |
| `clear_cache` | `echo 3 > drop_caches` | `Clear-RecycleBin; wsreset` | Existing |
| `flush_dns` | `systemd-resolve --flush` | `ipconfig /flushdns` | Existing |
| `dns_cache_clear` | Pi-hole/AdGuard API | Pi-hole/AdGuard API | Integration DNS cache |
| `event_log_clear` | n/a | `wevtutil cl` | Windows event log cleanup |
| `sfc_scan` | n/a | `sfc /scannow` | Windows system file checker |
| `journal_vacuum` | `journalctl --vacuum-size` | n/a | Linux journal cleanup |
| `package_cache_clean` | `apt clean` / `dnf clean` | n/a | Package manager cache |
| `windows_update_check` | n/a | `Get-WindowsUpdate` | Check for Windows updates |
| `disk_cleanup` | `fstrim`, `du` based | `cleanmgr /sagerun` | OS-specific disk reclaim |

### Medium-Risk Actions (automated with notification + audit)

| Action | Linux | Windows | Description |
|--------|-------|---------|-------------|
| `container_recreate` | `docker stop/pull/create` | `docker stop/pull/create` | Full recreate with same config |
| `service_dependency_restart` | Walk systemd deps | Walk `sc qc` deps | Restart chain in order |
| `storage_cleanup` | `docker system prune`, old logs | `docker system prune`, temp | Smart multi-target cleanup |
| `cert_renew` | `certbot renew` | `certbot renew` / IIS rebind | TLS certificate renewal |
| `vpn_reconnect` | `tailscale up` / `wg-quick` | `tailscale up` / WG svc | VPN tunnel recovery |
| `zfs_scrub` | `zpool scrub` | n/a | ZFS integrity check |
| `btrfs_scrub` | `btrfs scrub start` | n/a | Btrfs integrity check |
| `chkdsk` | n/a | `chkdsk /f` (scheduled) | Windows disk check |
| `fsck_schedule` | `touch /forcefsck` | n/a | Schedule fsck on next boot |
| `backup_verify` | checksum + restore test | checksum + restore test | Backup integrity check |
| `servarr_queue_cleanup` | API call | API call | Clear stuck queue items |
| `media_library_scan` | Plex/Jellyfin API | Plex/Jellyfin API | Trigger library refresh |
| `network_interface_restart` | `ip link set down/up` | `Restart-NetAdapter` | NIC cycle |
| `compose_restart` | `docker compose restart` | `docker compose restart` | Compose project restart |
| `scheduled_task_repair` | `systemctl reenable` (timers) | `schtasks /change /enable` | Fix broken scheduled tasks |
| `iis_app_pool_recycle` | n/a | `Restart-WebAppPool` | IIS app pool recycle |
| `wsl_restart` | n/a | `wsl --shutdown` | WSL instance restart |
| `memory_pressure_relief` | `swapoff/swapon`, OOM adj | Page file flush, trim | Memory emergency |

### High-Risk Actions (requires approval)

| Action | Linux | Windows | Description |
|--------|-------|---------|-------------|
| `host_reboot` | `shutdown -r` | `Restart-Computer` | Graceful OS reboot |
| `vm_restart` | Proxmox API | Hyper-V `Restart-VM` | VM restart |
| `vm_migrate` | Proxmox API | Hyper-V `Move-VM` | Live migrate VM |
| `package_security_patch` | `apt upgrade --security` | `Install-WindowsUpdate -SecurityOnly` | Security-only updates |
| `snapshot_rollback` | `zfs rollback` / TrueNAS API | Hyper-V checkpoint restore | Rollback to snapshot |
| `firewall_rule_add` | `nftables` / `iptables` | `New-NetFirewallRule` | Temporary firewall rule |
| `driver_rollback` | n/a | `pnputil /rollback-driver` | Windows driver rollback |
| `raid_rebuild` | `mdadm --add` | `Repair-VirtualDisk` | RAID/Storage Spaces rebuild |
| `group_policy_refresh` | n/a | `gpupdate /force` | Force GP refresh |
| `ad_replication_force` | n/a | `repadmin /syncall` | AD replication sync |

---

## Section 3: Universal Integration Heal Layer

### Architecture

The healing pipeline speaks in **abstract operations** (e.g., `nas_scrub`), not platform-specific calls (e.g., `truenas_scrub`). An `integration_registry` maps abstract ops to platform-specific API calls. New platforms are added by extending the registry or writing a plugin.

```python
INTEGRATION_HANDLERS = {
    "nas_scrub": {
        "truenas":  {"method": "POST", "endpoint": "/pool/{pool}/scrub", "auth": "bearer"},
        "synology": {"method": "POST", "endpoint": "/webapi/SYNO.Storage.CGI/v1?method=scrub", "auth": "session"},
        "qnap":     {"method": "POST", "endpoint": "/cgi-bin/disk/disk_manage.cgi?func=scrub", "auth": "session"},
        "omv":      {"method": "rpc", "service": "FileSystemMgmt", "method_name": "scrub", "auth": "session"},
        "unraid":   {"method": "exec", "command": "btrfs scrub start /mnt/disk{n}", "auth": "local"},
    },
}
```

### Integration Categories & Platforms

**NAS/Storage** — TrueNAS, Synology (DSM), QNAP (QTS), OpenMediaVault, Unraid, FreeNAS, Drobo, Buffalo, Asustor, TerraMaster, Zyxel NAS

Abstract operations: `nas_pool_repair`, `nas_scrub`, `nas_replication_sync`, `nas_snapshot_create`, `nas_snapshot_rollback`, `nas_share_restart`, `nas_disk_replace`, `nas_cache_clear`, `nas_quota_enforce`

**Hypervisor** — Proxmox VE, VMware ESXi/vCenter, Hyper-V, XCP-ng/XenServer, KVM/libvirt, Nutanix AHV, oVirt

Abstract operations: `vm_restart`, `vm_migrate`, `vm_snapshot`, `vm_snapshot_rollback`, `vm_resource_adjust`, `vm_console_reset`, `hypervisor_maintenance_mode`

**Container Runtime** — Docker, Podman, LXC/LXD, containerd, CRI-O, Kubernetes (K3s, K8s, MicroK8s, Rancher)

Abstract operations: `container_restart`, `container_recreate`, `container_scale`, `container_image_pull`, `container_rollback_image`, `container_network_reconnect`, `pod_restart`, `pod_evict`, `deployment_rollback`

**Reverse Proxy** — Traefik, Nginx Proxy Manager, Caddy, HAProxy, Apache, Nginx (raw), Envoy, Kong

Abstract operations: `proxy_reload_config`, `proxy_upstream_health_reset`, `proxy_cert_reload`, `proxy_backend_drain`, `proxy_rate_limit_adjust`, `proxy_cache_purge`

**DNS** — Pi-hole, AdGuard Home, CoreDNS, Unbound, BIND9, dnsmasq, PowerDNS, Windows DNS Server, Technitium

Abstract operations: `dns_cache_flush`, `dns_blocklist_update`, `dns_upstream_failover`, `dns_zone_reload`, `dns_forwarder_switch`, `dns_service_restart`

**Media Server** — Plex, Jellyfin, Emby, Kodi (headless), Subsonic/Airsonic, Navidrome

Abstract operations: `media_library_scan`, `media_db_optimize`, `media_cache_clear`, `media_transcode_kill`, `media_session_terminate`, `media_metadata_refresh`

**Media Management** — Radarr, Sonarr, Lidarr, Readarr, Bazarr, Prowlarr, Overseerr, Ombi, Tdarr, Whisparr

Abstract operations: `servarr_queue_clear`, `servarr_failed_retry`, `servarr_indexer_reset`, `servarr_import_scan`, `servarr_cache_clear`, `servarr_task_restart`

**Download Client** — qBittorrent, Transmission, Deluge, SABnzbd, NZBGet, rTorrent/ruTorrent, Aria2

Abstract operations: `download_resume_all`, `download_clear_stuck`, `download_recheck_torrents`, `download_force_reannounce`, `download_connection_reset`

**VPN/Tunnel** — Tailscale, WireGuard, OpenVPN, ZeroTier, Nebula, Headscale, Cloudflare Tunnel, Netbird, Firezone

Abstract operations: `vpn_reconnect`, `vpn_key_rotate`, `vpn_route_refresh`, `vpn_peer_reset`, `vpn_tunnel_restart`

**Monitoring** — Uptime Kuma, Grafana, Zabbix, Nagios, PRTG, Checkmk, Datadog agent, Prometheus, LibreNMS

Abstract operations: `monitor_force_check`, `monitor_clear_downtime`, `monitor_restart_agent`, `monitor_acknowledge_alert`, `monitor_silence_rule`

**Smart Home** — Home Assistant, OpenHAB, Hubitat, Domoticz, HomeSeer, ioBroker

Abstract operations: `home_reload_config`, `home_restart_integration`, `home_automation_toggle`, `home_device_rediscover`, `home_zwave_heal`, `home_zigbee_rejoin`

**Identity/Auth** — Authentik, Authelia, Keycloak, FreeIPA, Active Directory, LLDAP, Zitadel

Abstract operations: `auth_session_flush`, `auth_cache_clear`, `auth_provider_reconnect`, `auth_ldap_sync`, `auth_token_revoke_expired`

**Backup** — Borg, Restic, Veeam, Duplicati, Kopia, Bacula, Amanda, Proxmox Backup Server, Synology Hyper Backup, Acronis

Abstract operations: `backup_trigger`, `backup_verify`, `backup_prune_old`, `backup_retry_failed`, `backup_integrity_check`, `backup_mount_check`

**Certificate** — Let's Encrypt (certbot), ACME.sh, Caddy auto-TLS, Smallstep, Vault PKI, Windows ADCS, mkcert

Abstract operations: `cert_renew`, `cert_revoke_replace`, `cert_chain_fix`, `cert_deploy_reload`, `cert_ocsp_refresh`

**Database** — SQLite, PostgreSQL, MySQL/MariaDB, MongoDB, Redis, InfluxDB, TimescaleDB, CockroachDB, Memcached, Valkey

Abstract operations: `db_connection_pool_reset`, `db_cache_flush`, `db_replication_sync`, `db_vacuum_analyze`, `db_slow_query_kill`, `db_index_rebuild`, `db_failover_promote`

**Git/DevOps** — Gitea, GitLab, GitHub (self-hosted runner), Forgejo, Drone CI, Jenkins, Woodpecker CI

Abstract operations: `git_gc_prune`, `git_runner_restart`, `ci_queue_clear`, `ci_stuck_job_kill`, `ci_cache_purge`

**Mail** — Mailcow, Mail-in-a-Box, Postfix, Dovecot, iRedMail, Mailu, Zimbra

Abstract operations: `mail_queue_flush`, `mail_queue_clear_stuck`, `mail_service_restart`, `mail_index_rebuild`, `mail_spam_filter_update`

**Document/Wiki** — Paperless-NGX, Nextcloud, Bookstack, Wiki.js, Outline, Docusaurus

Abstract operations: `doc_reindex`, `doc_cache_clear`, `doc_thumbnail_regen`, `doc_storage_optimize`

**Security** — Vaultwarden, CrowdSec, Fail2Ban, Wazuh, OSSEC, Suricata, Snort

Abstract operations: `security_unban_ip`, `security_rule_reload`, `security_signature_update`, `security_quarantine_release`, `security_scan_trigger`

**Cloud/CDN** — Cloudflare, AWS (CLI), Azure, GCP, DigitalOcean, Hetzner, OVH

Abstract operations: `cdn_cache_purge`, `cloud_instance_restart`, `cloud_dns_failover`, `cloud_ssl_redeploy`, `cloud_firewall_rule`

**Network Hardware** — UniFi, MikroTik, TP-Link Omada, pfSense/OPNsense, OpenWrt, Ubiquiti EdgeOS, Aruba, Fortinet

Abstract operations: `net_restart_ap`, `net_reconnect_client`, `net_port_bounce`, `net_dhcp_release_renew`, `net_vlan_reassign`, `net_firmware_apply`, `net_routing_flush`

**Power/UPS** — APC (apcupsd), CyberPower, NUT, Eaton, Shelly, Tasmota, TP-Link Kasa/Smart

Abstract operations: `power_outlet_cycle`, `power_ups_test`, `power_load_shed`, `power_schedule_shutdown`, `power_battery_calibrate`

**Surveillance** — Frigate, Blue Iris, Shinobi, ZoneMinder, MotionEye, Scrypted, AgentDVR

Abstract operations: `cam_restart_detector`, `cam_storage_cleanup`, `cam_restream`, `cam_motion_recalibrate`, `cam_recording_repair`

### Multi-Instance Support

Real infrastructure has multiple instances of the same platform type: 3 TrueNAS boxes, 2 Proxmox nodes, quad Pi-hole across sites. The integration config supports **named instances** with independent URLs, credentials, sites, and dependency positions.

```yaml
integrations:
  nas:
    - id: "truenas-main"
      platform: truenas
      url: "https://truenas-main.local"
      auth: { token_env: "TRUENAS_MAIN_TOKEN" }
      site: site-a
      tags: [production, media-storage]

    - id: "truenas-backup"
      platform: truenas
      url: "https://truenas-backup.local"
      auth: { token_env: "TRUENAS_BACKUP_TOKEN" }
      site: site-a
      tags: [backup]

    - id: "synology-site-b"
      platform: synology
      url: "https://nas.site-b.local:5001"
      auth: { user: "admin", pass_env: "SYNOLOGY_PASS" }
      site: site-b
      tags: [production]

  hypervisor:
    - id: "pve-node1"
      platform: proxmox
      url: "https://pve1.local:8006"
      auth: { token: "..." }
      site: site-a

    - id: "pve-node2"
      platform: proxmox
      url: "https://pve2.local:8006"
      auth: { token: "..." }
      site: site-a

    - id: "hyperv-site-b"
      platform: hyperv
      url: "local"            # managed via agent
      site: site-b

  dns:
    - id: "pihole-primary-a"
      platform: pihole
      url: "http://pihole1.site-a.local"
      site: site-a
      tags: [primary]

    - id: "pihole-secondary-a"
      platform: pihole
      url: "http://pihole2.site-a.local"
      site: site-a
      tags: [secondary]

    - id: "pihole-primary-b"
      platform: pihole
      url: "http://pihole1.site-b.local"
      site: site-b
      tags: [primary]

    - id: "adguard-site-b"
      platform: adguard
      url: "http://adguard.site-b.local"
      site: site-b
      tags: [secondary]

  media:
    - id: "plex-main"
      platform: plex
      url: "http://plex.local:32400"
      auth: { token_env: "PLEX_TOKEN" }
      site: site-a

    - id: "jellyfin-site-b"
      platform: jellyfin
      url: "http://jellyfin.site-b.local:8096"
      auth: { api_key_env: "JELLYFIN_KEY" }
      site: site-b
```

### Instance-Aware Healing

When a heal action targets an integration, it must specify WHICH instance:

```python
# Heal event targets a specific instance
HealEvent(
    target="truenas-backup",           # instance ID, not just "truenas"
    source="alert",
    rule_id="nas-pool-degraded",
    condition="pool_status != 'ONLINE'",
    metrics={"pool_status": "DEGRADED"},
)
```

The executor resolves the instance ID to its platform, URL, and credentials:

```
1. Look up instance "truenas-backup" in integration config
2. Platform = truenas -> use truenas handler from registry
3. URL = https://truenas-backup.local
4. Auth = bearer token from env TRUENAS_BACKUP_TOKEN
5. Execute: POST /pool/{pool}/scrub with resolved credentials
```

### Dependency Graph with Instances

Dependencies reference specific instances, not generic platform types:

```yaml
dependencies:
  - target: plex-main
    depends_on: [truenas-main, "network:site-a"]
    type: service

  - target: jellyfin-site-b
    depends_on: [synology-site-b, "network:site-b"]
    type: service

  - target: truenas-main
    depends_on: ["network:site-a", "power:site-a"]
    type: service

  - target: truenas-backup
    depends_on: ["network:site-a", "power:site-a"]
    type: service
    # Note: truenas-backup does NOT depend on truenas-main
    # They are independent storage systems
```

### Instance Groups and Bulk Operations

For operations that should apply to all instances of a type (e.g., "update all Pi-hole blocklists"):

```yaml
# Define groups
integration_groups:
  all-pihole: ["pihole-primary-a", "pihole-secondary-a", "pihole-primary-b"]
  all-nas: ["truenas-main", "truenas-backup", "synology-site-b"]
  site-a-infra: ["truenas-main", "truenas-backup", "pve-node1", "pve-node2"]
```

Heal rules can target groups:

```yaml
alertRules:
  - id: pihole-gravity-stale
    condition: "pihole_gravity_age_hours > 168"
    target_group: all-pihole              # applies to every instance in group
    escalation_chain:
      - action: dns_blocklist_update
        verify_timeout: 60
```

When targeting a group, the pipeline evaluates and heals each instance independently — one failing Pi-hole doesn't block healing of the others.

### Credential Isolation

Each instance has independent credentials. This is critical because:

- Different TrueNAS boxes may have different admin tokens
- Site A and Site B may use different auth methods for the same platform
- A compromised credential for one instance doesn't affect others
- Credentials are ALWAYS referenced via environment variables (`_env` suffix), never stored in YAML

```yaml
# Supported auth patterns per instance
auth:
  # API token from environment variable
  token_env: "TRUENAS_MAIN_TOKEN"

  # Username + password from env
  user: "admin"
  pass_env: "NAS_PASS"

  # API key from env
  api_key_env: "JELLYFIN_KEY"

  # Bearer token from env
  bearer_env: "PROXMOX_TOKEN"

  # Cookie-based (session login) -- URL + credentials
  session:
    user: "admin"
    pass_env: "QNAP_PASS"

  # Local (agent-managed, no remote auth needed)
  local: true
```

### Integration Detection

The system determines which platform is running via:

1. **YAML config** — operator explicitly sets `platform: synology` per instance
2. **Auto-detection** — collector probes API signatures during setup
3. **Agent capability manifest** — agent reports locally installed tools

### Unknown Platform Fallback

If platform not recognized or operation not implemented:

1. Check `integration_registry` for platform handler — NOT FOUND
2. Check plugins for handler — NOT FOUND
3. Fallback options (configurable per-category):
   - `generic_api` — try generic REST call if pattern known
   - `agent_exec` — fall back to agent shell command
   - `notify` — can't heal, notify operator
   - `skip` — silently skip, log
4. Create suggestion: "Platform X has no handler for operation Y. Consider adding a plugin."

### Plugin Extension

```python
class MyCustomNasPlugin(NobaPlugin):
    def register_heal_handlers(self):
        return {
            "nas_scrub": {
                "my_custom_nas": {
                    "method": "POST",
                    "endpoint": "/api/v1/storage/scrub",
                    "auth": "api_key"
                }
            }
        }
```

---

## Section 4: Dependency Graph & Root Cause Analysis

### Dependency Model

Dependencies defined in YAML and augmented by auto-discovery. Each node is a target (container, service, host, integration, or external boundary).

```yaml
dependencies:
  # External boundaries -- things NOBA cannot heal
  - target: "isp:site-a"
    type: external
    health_check: "ping 1.1.1.1"
    site: site-a

  - target: "isp:site-b"
    type: external
    health_check: "ping 1.1.1.1"
    site: site-b

  - target: "power:site-a"
    type: external
    health_check: "agent_reachable"

  # Infrastructure layer
  - target: "network:site-a"
    depends_on: ["isp:site-a", "power:site-a"]
    type: infrastructure
    health_check: "ping 10.0.0.1"
    site: site-a

  # Service layer
  - target: truenas
    depends_on: ["network:site-a"]
    type: service
    health_check: "integration:truenas"

  - target: plex
    depends_on: [truenas, "network:site-a"]
    type: service

  - target: jellyfin
    depends_on: [truenas]
    type: service
```

### Node Types

| Type | Can NOBA heal? | Examples |
|------|----------------|---------|
| `external` | No — notify only | ISP, power, upstream DNS, cloud providers |
| `infrastructure` | Limited | Network gear, switches, storage arrays |
| `service` | Yes — full pipeline | Containers, systemd services, VMs |
| `agent` | Yes — agent self-heal | Remote host running noba-agent |

### Root Cause Resolution Algorithm

When multiple alerts fire within a correlation window:

```
1. Collect all firing alerts into a set
2. For each alert target, walk UP the dependency graph
3. Find the highest ancestor that is ALSO alerting
4. That ancestor is the root cause candidate
5. If root cause is "external" -> suppress ALL downstream healing, notify only
6. If root cause is "infrastructure" -> heal infrastructure first, suppress downstream
7. If root cause is "service" -> heal that service, suppress dependents
8. If no common ancestor -> treat as independent issues, heal separately
```

### The ISP/Connectivity Problem (Site Isolation)

```
SCENARIO: ISP down at Site A, server runs at Site B

Server perspective:
  - Agent-SiteA: UNREACHABLE
  - Plex@SiteA: UNREACHABLE (via integration check)
  - NAS@SiteA: UNREACHABLE

Decision:
  1. Agent unreachable -> mark "connectivity-suspect" for entire site
  2. Walk dependency graph: all failing targets share ancestor "isp:site-a"
  3. "isp:site-a" is type=external -> CANNOT heal
  4. Suppress ALL healing for Site A
  5. Notify: "Site A unreachable -- suspected ISP/connectivity issue"
  6. Start connectivity watchdog timer (check every 60s)

When agent reconnects:
  1. Agent sends backlog: "I was fine locally the whole time"
     OR "service X actually failed, I healed it locally"
  2. Server reconciles ledger with agent's local heal reports
  3. Clear "connectivity-suspect" state
  4. Resume normal monitoring
```

### Partial Failures (Agent Reachable, Some Services Down)

```
SCENARIO: Agent reachable, Plex down, NAS fine

  1. Agent IS reachable -> site connectivity OK
  2. Walk deps: Plex depends on NAS -> NAS is fine
  3. Root cause is Plex itself (not upstream)
  4. Server asks agent: "is Plex actually down from your side?"
  5. Agent confirms -> heal Plex

SCENARIO: Agent reachable, Plex down, NAS also down

  1. Agent reachable -> connectivity OK
  2. Walk deps: Plex depends on NAS, NAS is down
  3. Root cause: NAS
  4. Heal NAS first
  5. Wait for NAS recovery + settle time
  6. Re-evaluate Plex -- still down? -> now heal Plex
  7. Plex recovered because NAS is back? -> suppress, log "resolved by dependency heal"
```

### Agent-Verified Healing

For any remote target, the server never blindly heals based on its own reachability check:

```
Server detects target "X" is down
  -> Can server reach X's agent?
    -> YES: Ask agent "is X actually down locally?"
      -> Agent confirms DOWN -> proceed with heal
      -> Agent says UP -> log "false positive (server-side reachability issue)", notify, suppress
    -> NO: Is the agent's entire site suspect?
      -> YES -> suppress all, notify
      -> NO -> specific agent is down, try agent self-recovery
```

### Auto-Discovery

The system learns dependencies by analyzing co-failure patterns:

- Track every alert: `{target, timestamp, duration}`
- Detect co-failures: "targets A and B fail within 2 minutes of each other, 85%+ of the time"
- Surface as suggestions: "jellyfin co-fails with truenas 87% of the time. Add dependency?"
- Operator confirms -> added to YAML
- Operator dismisses -> suppressed for 30 days, re-evaluated

Auto-discovered dependencies are **never acted on without operator confirmation**.

### Storage

- **Static deps**: YAML config (source of truth, version controlled)
- **Auto-discovered candidates**: `heal_suggestions` table (category="dependency_candidate")
- **Runtime graph**: In-memory, rebuilt on config reload, queryable via API
- **API**: `GET /api/healing/dependencies` returns full graph for UI

---

## Section 5: Approval Model & Permissions

### Risk-Based Tiers

```
Low-risk    -> auto-execute, audit trail, optional notification
Medium-risk -> auto-execute, mandatory notification, audit trail
High-risk   -> requires approval before execution
```

The trust governor can override: a high-risk action with proven track record can earn medium-risk behavior. A low-risk action with poor success rate gets promoted to require approval.

### Approval Flow

```
High-risk action triggered
  -> Create approval request with full context
  -> Notify operators (or admins, based on action risk)
  -> Start timeout timer

  Timeout stage 1 (configurable, default 10 min):
    -> No response? Escalate to next role level
    -> operator -> admin
    -> Already at highest? Move to stage 2

  Timeout stage 2 (configurable, default 30 min):
    -> Still no response? Auto-DENY
    -> Log: "approval expired -- auto-denied"
    -> Notify: "healing action expired without approval"

  Approved:
    -> Execute through normal pipeline
    -> Audit: who approved, when, from where

  Denied:
    -> Log denial with reason
    -> Governor records for trust evaluation
```

### Adaptive to User Base

```python
admins = count_users_with_role("admin")
operators = count_users_with_role("operator")

if admins == 0 and operators == 0:
    # No one to approve -- auto-deny with critical alert

if admins == 1 and operators == 0:
    # Single admin -- all approvals go to them
    # No escalation chain possible
    # Critical actions: confirmation cooldown

if admins >= 1 and operators >= 1:
    # Normal flow: operators first, escalate to admins
```

### Confirmation Cooldown (Single-Admin Safety)

When there's only one admin and no operators, critical actions use a cooldown:

```
Admin approves critical action
  -> System: "Confirmed. This will execute in 5 minutes.
              Reply CANCEL to abort."
  -> 5 min cooldown
  -> If not cancelled -> execute
  -> If cancelled -> log "self-cancelled by admin"
```

### Defer Option

Besides approve/deny, approvers can **defer** — push timeout back by configurable amount. Max 3 defers, then auto-deny.

### Approval Context

Every approval request includes:

```
Action:     host_reboot("proxmox-1")
Risk:       HIGH
Triggered:  alert rule "cpu_overload"
Evidence:   CPU at 98% for 12 minutes
            3 prior heals failed:
              - restart_container (failed)
              - service_restart (failed)
              - scale_container (failed)
Escalation: Step 4 of 4
Dependency: No downstream services affected
Rollback:   IRREVERSIBLE (reboot)
Expires:    30 min (auto-deny)

[APPROVE]  [DENY]  [DEFER 30 min]
```

### Emergency Override

Configurable per-rule, off by default:

```yaml
emergency_override:
  enabled: true
  conditions:
    - severity: critical
    - consecutive_failures: 5
    - no_response_minutes: 15
  action: execute
  notification: critical       # blast all channels
  cooldown_s: 300              # don't do again for 5 min
```

Every emergency override logged with distinct audit category.

### Audit Trail (Everything, Always)

Every healing action, regardless of risk or trust level, gets an audit record:

```python
{
    "event_id": "uuid",
    "timestamp": "2026-03-22T14:30:00Z",
    "action_type": "host_reboot",
    "target": "proxmox-1",
    "risk_level": "high",
    "trust_level": "approve",
    "trigger": {
        "source": "alert",
        "rule_id": "cpu_overload",
        "condition": "cpu_percent > 95",
        "metrics_at_trigger": {"cpu_percent": 98.2}
    },
    "approval": {
        "requested_at": "...",
        "approved_by": "raizen",
        "approved_at": "...",
        "defers": 0,
        "was_emergency": false
    },
    "execution": {
        "started_at": "...",
        "completed_at": "...",
        "success": true,
        "verified": true,
        "duration_s": 45.2,
        "metrics_after": {"cpu_percent": 32.1}
    },
    "rollback": {
        "available": false,
        "reason": "irreversible action"
    },
    "dependency_context": {
        "root_cause": "proxmox-1",
        "suppressed_targets": []
    }
}
```

---

## Section 6: Predictive & Proactive Healing

### Wiring the Prediction Engine

Currently on-demand via API. Add scheduler-driven evaluation:

```
Every 15 minutes (configurable):
  For each metric with a prediction model:
    1. Run prediction for 24h/72h/168h horizons
    2. If predicted to breach threshold within warning window:
       - Emit HealEvent(source="prediction", severity based on horizon)
       - 24h -> severity: warning
       - 72h -> severity: info
       - 168h+ -> suggestion only, no heal event
    3. Conservative action selection:
       - Predictions ONLY trigger low-risk actions
       - Medium/high-risk require actual threshold breach
       - Trust level capped one below rule's current level
```

### Wiring Anomaly Detection

Currently notifications only. Wire to pipeline:

```
Anomaly detected (metric deviates from historical band):
  1. Is this a known seasonal pattern?
     -> YES: suppress (don't heal expected spikes)
     -> NO: emit HealEvent(source="anomaly")
  2. Same conservative treatment as predictions
  3. Persists beyond 2 evaluation cycles -> escalate severity
```

### Health Score Integration

```
Every 5 minutes (with collector cycle):
  Compute health score per category
  If any category drops below configurable threshold:
    - capacity < 40 -> trigger storage_cleanup, temp_cleanup
    - cert_health < 50 -> trigger cert_renew suggestions
    - backup_freshness < 30 -> trigger backup_verify, trigger_backup
    - monitoring_coverage < 60 -> notify "agents offline"

  Health score feeds INTO dependency graph:
    - Degraded health on dependency root -> increases urgency
```

### Stale Data Protection

```
Before any prediction/anomaly evaluation:
  1. Check collector last_update timestamp
  2. If older than 2x collection interval -> data is stale
  3. Stale data -> suspend predictive healing, notify
  4. Resume when fresh data arrives
```

---

## Section 7: Maintenance Windows

### Window Types

```yaml
maintenance_windows:
  global:
    - cron: "0 3 * * 0"        # Weekly Sunday 3am
      duration: 2h
      reason: "Weekly maintenance"
      action: suppress_all

  per_target:
    frigate:
      - cron: "0 2 * * *"      # Daily 2am
        duration: 2h
        reason: "Recording export"
        action: suppress
    proxmox:
      - cron: "0 4 1 * *"      # Monthly 1st at 4am
        duration: 4h
        reason: "Scheduled updates"
        action: queue
```

### Window Actions

| Action | Behavior |
|--------|----------|
| `suppress_all` | Drop all heal events silently, log as "suppressed by maintenance" |
| `suppress` | Drop heal events for specific target only |
| `queue` | Queue heal events, re-evaluate when window closes |
| `notify_only` | Override all trust levels to "notify" during window |

### Ad-Hoc Maintenance

```
POST /api/healing/maintenance
{
  "target": "all" | "specific-target",
  "duration": "30m",
  "reason": "deploying update",
  "action": "suppress_all"
}

DELETE /api/healing/maintenance/{id}   # end early
GET /api/healing/maintenance           # list active
```

### Post-Maintenance Evaluation

When a queued window closes:

1. Collect all queued heal events
2. Re-evaluate each condition against CURRENT metrics
3. Condition still true -> feed into pipeline
4. Condition resolved during window -> dismiss, log "resolved during maintenance"
5. Summary notification: "Maintenance ended. 3 queued: 2 resolved, 1 proceeding"

---

## Section 8: Rollback & State Snapshots

### Pre-Heal Snapshot

Before executing any action, capture state:

```python
{
    "snapshot_id": "uuid",
    "timestamp": "2026-03-22T14:30:00Z",
    "target": "frigate",
    "action_type": "scale_container",
    "state": {
        "container_config": {"memory": "2g", "cpus": "2.0", "restart_policy": "always"},
        "service_status": "running",
        "metrics": {"mem_percent": 92, "cpu_percent": 45}
    }
}
```

### Snapshot Fields by Action Category

| Category | Captured State |
|----------|---------------|
| Container actions | Config (memory, CPU, env, restart policy, image tag) |
| Service actions | Status, enabled state, unit file hash |
| File actions | Content hash, permissions, ownership |
| Network actions | Interface config, route table, firewall rules |
| Scale actions | Current limits before change |
| Package actions | Package version before update |

### Rollback Flow

```
Heal action executes
  -> Verify: FAILED (condition still true or WORSE)
  -> Is action reversible?
    -> YES:
      -> Auto-rollback if configured (per-rule setting)
      -> OR queue rollback for operator approval
      -> Execute reverse action from snapshot
      -> Verify rollback succeeded
      -> Log: "rolled back to pre-heal state"
    -> NO (irreversible):
      -> Log: "action irreversible, rollback not possible"
      -> Notify operator with full context
      -> Do NOT escalate further automatically
```

### Reversibility Registry

```python
REVERSE_ACTIONS = {
    "scale_container":    "scale_container",      # scale back to snapshot values
    "service_restart":    None,                    # idempotent, no reverse needed
    "container_recreate": "container_recreate",    # recreate with snapshot config
    "firewall_rule_add":  "firewall_rule_remove",
    "nice_adjust":        "nice_adjust",           # restore original priority
    "network_interface_restart": None,             # idempotent

    # Irreversible
    "process_kill":       None,  # can't un-kill
    "clear_cache":        None,  # data gone
    "host_reboot":        None,  # state reset
    "temp_cleanup":       None,  # files deleted
    "snapshot_rollback":  None,  # previous snapshot gone
}
```

### Manual Rollback via UI/API

```
POST /api/healing/rollback/{ledger_id}
  -> Find snapshot for that heal action
  -> Show operator what will be reversed
  -> Require confirmation
  -> Execute reverse action, verify, log
```

---

## Section 9: Internal Resilience

### Component Health Monitor

Each subsystem writes a heartbeat timestamp. A watchdog thread checks all heartbeats every 10 seconds.

```python
COMPONENTS = {
    "collector":  {"interval": 5,   "tolerance": 3},   # alert after 3 missed heartbeats
    "scheduler":  {"interval": 60,  "tolerance": 2},
    "healing":    {"interval": 30,  "tolerance": 2},
    "db":         {"interval": 10,  "tolerance": 3},
    "api":        {"interval": 5,   "tolerance": 3},
}
```

### Failure Responses

**Collector stalled:**
- Healing suspended (stale data protection)
- Scheduler still runs (cron jobs, approvals)
- Attempt collector restart (re-init collection loop)
- Notify: "collector stalled -- healing paused"

**Scheduler stalled:**
- Collector still runs (metrics fresh)
- Healing still runs (alert-triggered)
- Attempt scheduler restart
- Notify: "scheduler stalled -- cron/maintenance affected"

**Healing pipeline stalled:**
- Collector and scheduler unaffected
- New heal events queue in-memory (bounded, drop oldest if full)
- Attempt pipeline restart
- Notify: "healing pipeline stalled"

**DB locked/corrupted:**
- All writes queue in-memory (bounded buffer)
- Read operations serve from cache where possible
- Attempt WAL checkpoint, then VACUUM
- If persistent: switch to read-only mode
- Notify: "database degraded -- operating from cache"
- On recovery: flush in-memory queue to DB

**API unresponsive:**
- Agents fall back to local heal policies
- Internal components unaffected
- systemd watchdog triggers restart if health endpoint fails

### Cascading Failure Prevention

A component's recovery action CANNOT depend on a failed component:
- Collector restart doesn't need scheduler
- Scheduler restart doesn't need collector
- Healing restart doesn't need either
- DB recovery doesn't need healing

If THREE+ components fail simultaneously:
- Likely systemic issue (OOM, disk full)
- Switch to degraded mode: metrics + notifications only
- Critical alert: "NOBA degraded -- multiple subsystem failures"

### Systemd Integration

```ini
[Service]
WatchdogSec=30
Restart=on-failure
RestartSec=5
```

Internal component recovery handles soft failures; systemd handles hard crashes.

---

## Section 10: Testing & Validation

### Three Testing Layers

**Layer 1: Unit Tests (CI-safe)**
- Each module in isolation with mocked external calls
- ~200+ tests expanding on current 75
- Run on every commit

**Layer 2: Chaos Testing Framework (controlled fault injection)**

Built-in test harness that intentionally breaks things and validates the response:

```yaml
chaos_tests:
  - name: "container_crash_recovery"
    inject: { action: stop_container, target: frigate }
    expect:
      - heal_triggered: true
      - action_taken: restart_container
      - verified: true
      - duration_lt: 60s
    teardown: { ensure: container_running(frigate) }

  - name: "dependency_cascade_suppression"
    inject: { action: stop_container, target: truenas }
    expect:
      - heal_triggered_for: truenas
      - heal_suppressed_for: [plex, jellyfin]
      - root_cause_identified: truenas
    teardown: { ensure: container_running(truenas, plex, jellyfin) }

  - name: "escalation_chain_full_walk"
    inject: { action: corrupt_service, target: test-service }
    expect:
      - escalation_step_0: restart_service (verified: false)
      - escalation_step_1: restart_container (verified: false)
      - escalation_step_2: host_reboot (approval_requested: true)

  - name: "agent_offline_local_heal"
    inject: { action: block_server_connection, target: agent-site-b, then: spike_cpu }
    expect:
      - agent_healed_locally: true
      - server_heal_suppressed: true
      - on_reconnect: agent_reports_local_heal

  - name: "isp_outage_no_false_heals"
    inject: { action: block_site_connectivity, target: site-a }
    expect:
      - site_marked: connectivity-suspect
      - heals_at_site_a: 0
      - notification_sent: "Site A unreachable"

  - name: "approval_timeout_escalation"
    inject: { action: trigger_high_risk_heal, target: proxmox-1, approval_response: none }
    expect:
      - operator_notified: true
      - after_10m: admin_notified
      - after_30m: auto_denied
      - action_executed: false

  - name: "heal_storm_circuit_breaker"
    inject: { action: flap_service, target: test-service, cycles: 10, interval: 5s }
    expect:
      - heals_executed: 3
      - circuit_breaker: open
      - trust_demoted_to: notify

  - name: "rollback_on_worse_outcome"
    inject: { action: scale_container, target: test-app, sabotage: "cause OOM" }
    expect:
      - verified: false
      - rollback_triggered: true
      - state_restored: true

  - name: "stale_metrics_phantom_heal"
    inject: { action: pause_collector, duration: 120s }
    expect:
      - heals_triggered: 0
      - staleness_detected: true

  - name: "power_flicker_rapid_cycles"
    inject: { action: flap_agent_connectivity, target: agent-site-a, cycles: 5, interval: 10s }
    expect:
      - connectivity_suspect: true
      - heals_at_site_a: 0

  - name: "capability_mismatch_recovery"
    inject: { action: break_docker_socket, target: agent-site-a }
    expect:
      - pre_flight_fails: true
      - action_aborted: true
      - capability_refreshed: true
      - docker_marked: degraded

  - name: "manual_operator_race"
    inject: { action: trigger_heal_for: test-service, then: manually_fix_service }
    expect:
      - verification: passes
      - ledger_records: "resolved externally"
      - no_duplicate_action: true
```

**Layer 3: Dry-Run Mode**

```
POST /api/healing/dry-run
{
  "event": {
    "source": "test",
    "rule_id": "cpu_overload",
    "condition": "cpu_percent > 95",
    "target": "proxmox-1",
    "metrics": {"cpu_percent": 97}
  }
}

Response:
{
  "would_correlate": true,
  "correlation_key": "proxmox-1:cpu",
  "dependency_analysis": {
    "root_cause": "proxmox-1",
    "suppressed": []
  },
  "would_select": {
    "action": "restart_service",
    "step": 0,
    "trust_level": "execute",
    "reason": "First step in chain (82% historical success)"
  },
  "pre_flight": {
    "capability_check": "pass",
    "target_exists": true,
    "maintenance_window": false,
    "dependency_clear": true
  },
  "rollback_plan": "reverse: stop_service -> restart_service (reversible)"
}
```

### Canary Rollout

New rules start in observation mode:

```
observation -> dry-run -> notify -> approve -> execute
```

- **Observation**: Rule evaluated but no events. Dashboard shows "would have fired 12 times this week."
- **Dry-run**: Pipeline runs fully but stops before execution.
- **notify/approve/execute**: Normal trust levels.

---

## Section 11: Notification Enrichment & Dedicated Channel

### Enriched Notifications

Every heal notification includes full context:

```
HEAL: restart_container("frigate")

Trigger:  mem_percent > 85 (current: 92%)
Source:   alert rule "frigate-memory"
Evidence: Memory climbing for 15 min (78% -> 92%)
Action:   restart_container (step 1 of 3)
Trust:    execute (auto)
Duration: 12.3s
Result:   Verified -- mem_percent dropped to 34%

Dependency: No downstream impact
Rollback:  Available (snapshot saved)
Ledger:    #1847
```

For failures:

```
HEAL FAILED: restart_container("frigate")

Trigger:  mem_percent > 85 (current: 92%)
Action:   restart_container (step 1 of 3)
Result:   Not verified -- mem_percent still 89% after 30s
Next:     Escalating to scale_container (step 2)

Evidence: Container restarted but memory returned to 89%
          within 15s. Possible memory leak.
Suggestion: Consider increasing memory limit.
```

### Channel Routing

```yaml
notifications:
  healing:
    channel: "heal-ops"
    low_risk: digest             # batch into hourly digest
    medium_risk: immediate
    high_risk: immediate + alert
    failures: immediate

  regular_alerts:
    channel: "alerts"            # existing channel untouched
```

Digest mode for low-risk: "In the last hour: 4 container restarts (all verified), 2 cache clears, 1 log rotation."

---

## Section 12: Full Healing Dashboard UI

### Components

**1. Healing Overview (top bar)**
- Pipeline status: Active | Paused | Maintenance | Degraded
- Active heals in progress (count + targets)
- Circuit breakers open (count)
- Pending approvals (count + urgency badge)

**2. Effectiveness Panel**
- Chart.js line chart: success rate over time (7d/30d/90d)
- MTTR chart: average time-to-resolution trending
- Per-rule bar chart: success rate by rule
- Per-action-type donut: which actions verify most

**3. Ledger Timeline**
- Vertical timeline view (not just table)
- Each entry: action, target, result (color-coded), duration
- Expandable for full detail (metrics before/after, approval, rollback)
- Filters: rule, target, risk, result, date range
- Export as JSON/CSV

**4. Dependency Graph**
- Interactive tree/graph visualization
- Nodes colored by health status (green/yellow/red/grey)
- Edges show dependency direction
- Click node -> recent heals, alerts, trust state
- Highlight root cause path during incidents
- "connectivity-suspect" sites greyed out

**5. Trust Management**
- Card per rule with current level, ceiling, history
- Promotion/demotion timeline per rule
- Manual promote/demote buttons (role-gated)
- Governor evaluation results

**6. Approval Queue**
- Pending approvals with full context cards
- Approve/Deny/Defer buttons
- Timer showing time remaining
- Escalation indicator
- Historical approved/denied with audit trail

**7. Maintenance Windows**
- Calendar view of scheduled windows
- Active window indicator with countdown
- "Enter Maintenance" quick button
- Queued events during active window (dismiss/keep toggles)

**8. Suggestions Panel**
- Active suggestions with evidence
- Dependency discovery candidates
- Trust promotion candidates
- Low-effectiveness warnings
- Accept/Dismiss/Snooze actions

**9. Capability Matrix**
- Per-agent capability manifest view
- Degraded capabilities highlighted
- Last probe timestamp
- Manual "refresh capabilities" button

**10. Chaos Test Runner** (admin only)
- Scenario selector dropdown
- Dry-run or live toggle
- Real-time execution log
- Results vs expectations comparison

---

## Section 13: Edge Cases

Every edge case has an explicit handling strategy:

| Edge Case | Handling |
|-----------|---------|
| **Cascading failures** | Dependency graph: heal root, suppress downstream |
| **Heal storms** | Correlation absorption window + circuit breaker (3 failures -> trip) |
| **Split-brain between sites** | Agent-verified healing. Can't reach site -> connectivity-suspect, suppress all |
| **Agent clock drift** | Server timestamps all events. Agent timestamps for local ordering. Skew > 30s -> warning |
| **DB corruption during heal** | In-memory queue buffer. Degrade to cache-only. Alert. Auto-repair (WAL checkpoint) |
| **Heal makes things WORSE** | Post-heal verification detects degradation. Auto-rollback if reversible. Circuit breaker trips. Trust demoted |
| **Race: operator manual fix vs auto-heal** | Verification passes (operator fixed it). Ledger records "resolved externally" |
| **Stale metrics -> phantom heals** | Collector staleness detection. Data age > 2x interval -> suspend healing |
| **Power flicker (rapid up/down)** | Connectivity flap detection. Debounce: stable-for-60s before acting |
| **Agent running old policy** | Policy version check on heartbeat. Mismatch -> push update. Old policy still valid (superset) |
| **Healing during backup window** | Maintenance window system. Backup windows defined, healing queued/suppressed |
| **Action timeout vs startup mismatch** | Per-action configurable settle time. Suggestion engine detects systematic false negatives |
| **Concurrent heals on same target** | Planner escalation guard: one active chain per correlation key |
| **Recursive healing** (heal triggers alert triggers heal) | Source tracking. Events from heal_verification never re-enter pipeline |
| **Agent self-update during heal** | Update queued, not executed during active heal. Heal completes first |
| **Capability change mid-heal** | Pre-flight per-action. Capability degrades between steps -> abort step, try next |
| **Network partition within site** | Agent heals locally per policy. Reports on reconnect |
| **Config reload during active heal** | Active chains complete with original config. New config applies to next event |
| **Approval expires during server restart** | On startup: scan expired approvals, auto-deny, log "expired during restart" |
| **Multiple rules matching same target** | Correlation groups by target. First rule's chain runs, others absorbed |

---

## New API Endpoints

Extends `routers/healing.py`:

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/healing/ledger` | read | Recent outcomes with filtering |
| GET | `/api/healing/effectiveness` | read | Per-rule/action success rates |
| GET | `/api/healing/suggestions` | read | Active suggestions |
| POST | `/api/healing/suggestions/{id}/dismiss` | operator | Dismiss suggestion |
| POST | `/api/healing/suggestions/{id}/accept` | operator | Accept suggestion (apply change) |
| GET | `/api/healing/trust` | read | Trust state per rule |
| POST | `/api/healing/trust/{rule_id}/promote` | admin | Manual promotion |
| POST | `/api/healing/trust/{rule_id}/demote` | admin | Manual demotion |
| GET | `/api/healing/dependencies` | read | Full dependency graph |
| POST | `/api/healing/dependencies/validate` | operator | Validate dependency config |
| GET | `/api/healing/maintenance` | read | Active/scheduled windows |
| POST | `/api/healing/maintenance` | operator | Create ad-hoc window |
| DELETE | `/api/healing/maintenance/{id}` | operator | End window early |
| POST | `/api/healing/dry-run` | operator | Simulate heal event |
| POST | `/api/healing/rollback/{ledger_id}` | admin | Manual rollback |
| GET | `/api/healing/capabilities/{hostname}` | read | Agent capability manifest |
| POST | `/api/healing/capabilities/{hostname}/refresh` | operator | Force capability re-probe |
| GET | `/api/healing/chaos/scenarios` | admin | List available chaos tests |
| POST | `/api/healing/chaos/run` | admin | Execute chaos test |
| GET | `/api/healing/health` | read | Pipeline internal health status |

---

## DB Schema Changes

### New Tables

```sql
CREATE TABLE heal_snapshots (
    id INTEGER PRIMARY KEY,
    ledger_id INTEGER REFERENCES heal_ledger(id),
    target TEXT NOT NULL,
    action_type TEXT NOT NULL,
    state TEXT NOT NULL,              -- JSON snapshot
    created_at INTEGER NOT NULL
);
CREATE INDEX idx_heal_snapshots_ledger ON heal_snapshots(ledger_id);

CREATE TABLE maintenance_windows (
    id INTEGER PRIMARY KEY,
    target TEXT NOT NULL,             -- "all" or specific target
    cron_expr TEXT,                   -- NULL for ad-hoc
    duration_s INTEGER NOT NULL,
    reason TEXT,
    action TEXT NOT NULL DEFAULT 'suppress',
    active INTEGER NOT NULL DEFAULT 1,
    created_by TEXT,
    created_at INTEGER NOT NULL,
    expires_at INTEGER                -- NULL for cron-based (recurring)
);
CREATE INDEX idx_maintenance_active ON maintenance_windows(active, expires_at);

CREATE TABLE dependency_graph (
    id INTEGER PRIMARY KEY,
    target TEXT NOT NULL UNIQUE,
    depends_on TEXT,                  -- JSON array
    node_type TEXT NOT NULL,          -- external, infrastructure, service, agent
    health_check TEXT,
    site TEXT,
    auto_discovered INTEGER DEFAULT 0,
    confirmed INTEGER DEFAULT 0,      -- operator confirmed auto-discovery
    created_at INTEGER NOT NULL
);

CREATE TABLE capability_manifests (
    hostname TEXT PRIMARY KEY,
    manifest TEXT NOT NULL,           -- JSON
    probed_at INTEGER NOT NULL,
    degraded_capabilities TEXT        -- JSON array of degraded tool names
);

CREATE TABLE integration_instances (
    id TEXT PRIMARY KEY,              -- e.g. "truenas-main", "pihole-primary-a"
    category TEXT NOT NULL,           -- e.g. "nas", "dns", "media"
    platform TEXT NOT NULL,           -- e.g. "truenas", "synology", "pihole"
    url TEXT,
    auth_config TEXT NOT NULL,        -- JSON (references env vars, never raw secrets)
    site TEXT,
    tags TEXT,                        -- JSON array
    enabled INTEGER NOT NULL DEFAULT 1,
    health_status TEXT DEFAULT 'unknown',  -- online, offline, degraded, unknown
    last_seen INTEGER,
    created_at INTEGER NOT NULL
);
CREATE INDEX idx_integration_category ON integration_instances(category, platform);
CREATE INDEX idx_integration_site ON integration_instances(site);

CREATE TABLE integration_groups (
    group_name TEXT NOT NULL,
    instance_id TEXT NOT NULL REFERENCES integration_instances(id),
    PRIMARY KEY (group_name, instance_id)
);
```

### Extended heal_ledger Columns

```sql
ALTER TABLE heal_ledger ADD COLUMN risk_level TEXT;
ALTER TABLE heal_ledger ADD COLUMN snapshot_id INTEGER REFERENCES heal_snapshots(id);
ALTER TABLE heal_ledger ADD COLUMN rollback_status TEXT;       -- NULL, "rolled_back", "irreversible"
ALTER TABLE heal_ledger ADD COLUMN dependency_root TEXT;       -- root cause target
ALTER TABLE heal_ledger ADD COLUMN suppressed_by TEXT;         -- ledger_id that suppressed this
ALTER TABLE heal_ledger ADD COLUMN maintenance_window_id INTEGER;
ALTER TABLE heal_ledger ADD COLUMN instance_id TEXT;            -- which integration instance was targeted
```

---

## Section 14: Dashboard Cards & Monitoring for All Platforms

### The Problem

NOBA currently has dashboard cards for a limited set of integrations. If we support 24 integration categories with dozens of platforms, the dashboard needs cards for ALL of them — not just TrueNAS, but QNAP, Synology, VMware, Hyper-V, etc. Each platform has different metrics to display.

### Card Architecture: Template-Based Rendering

Instead of hardcoding a Vue component per integration, use a **template-driven card system** where each platform type defines what metrics to display:

```python
CARD_TEMPLATES = {
    # NAS platforms
    "truenas": {
        "title": "TrueNAS",
        "icon": "server",
        "metrics": [
            {"key": "pool_status", "label": "Pool", "type": "status"},  # ONLINE/DEGRADED/FAULTED
            {"key": "pool_used_pct", "label": "Used", "type": "percent_bar"},
            {"key": "dataset_count", "label": "Datasets", "type": "number"},
            {"key": "replication_status", "label": "Replication", "type": "status"},
            {"key": "scrub_age_hours", "label": "Last Scrub", "type": "age"},
        ],
    },
    "synology": {
        "title": "Synology",
        "icon": "server",
        "metrics": [
            {"key": "volume_status", "label": "Volume", "type": "status"},
            {"key": "volume_used_pct", "label": "Used", "type": "percent_bar"},
            {"key": "drive_health", "label": "Drives", "type": "status"},
            {"key": "hyper_backup_status", "label": "Backup", "type": "status"},
            {"key": "active_packages", "label": "Packages", "type": "number"},
        ],
    },
    "qnap": {
        "title": "QNAP",
        "icon": "server",
        "metrics": [
            {"key": "raid_status", "label": "RAID", "type": "status"},
            {"key": "volume_used_pct", "label": "Used", "type": "percent_bar"},
            {"key": "drive_temp_max", "label": "Drive Temp", "type": "temperature"},
            {"key": "snapshot_count", "label": "Snapshots", "type": "number"},
            {"key": "qtier_status", "label": "Qtier", "type": "status"},
        ],
    },
    "unraid": {
        "title": "Unraid",
        "icon": "server",
        "metrics": [
            {"key": "array_status", "label": "Array", "type": "status"},
            {"key": "array_used_pct", "label": "Used", "type": "percent_bar"},
            {"key": "parity_status", "label": "Parity", "type": "status"},
            {"key": "docker_count", "label": "Dockers", "type": "number"},
            {"key": "vm_count", "label": "VMs", "type": "number"},
        ],
    },

    # Hypervisors
    "proxmox": {
        "title": "Proxmox VE",
        "icon": "cpu",
        "metrics": [
            {"key": "node_status", "label": "Node", "type": "status"},
            {"key": "cpu_percent", "label": "CPU", "type": "percent_bar"},
            {"key": "mem_percent", "label": "RAM", "type": "percent_bar"},
            {"key": "vm_count", "label": "VMs", "type": "number"},
            {"key": "lxc_count", "label": "Containers", "type": "number"},
        ],
    },
    "vmware": {
        "title": "VMware ESXi",
        "icon": "cpu",
        "metrics": [
            {"key": "host_status", "label": "Host", "type": "status"},
            {"key": "cpu_percent", "label": "CPU", "type": "percent_bar"},
            {"key": "mem_percent", "label": "RAM", "type": "percent_bar"},
            {"key": "vm_count", "label": "VMs", "type": "number"},
            {"key": "datastore_used_pct", "label": "Storage", "type": "percent_bar"},
        ],
    },
    "hyperv": {
        "title": "Hyper-V",
        "icon": "cpu",
        "metrics": [
            {"key": "host_status", "label": "Host", "type": "status"},
            {"key": "vm_count", "label": "VMs", "type": "number"},
            {"key": "running_vms", "label": "Running", "type": "number"},
            {"key": "checkpoint_count", "label": "Checkpoints", "type": "number"},
            {"key": "replication_health", "label": "Replication", "type": "status"},
        ],
    },
    "xcpng": {
        "title": "XCP-ng",
        "icon": "cpu",
        "metrics": [
            {"key": "host_status", "label": "Host", "type": "status"},
            {"key": "cpu_percent", "label": "CPU", "type": "percent_bar"},
            {"key": "mem_percent", "label": "RAM", "type": "percent_bar"},
            {"key": "vm_count", "label": "VMs", "type": "number"},
            {"key": "sr_used_pct", "label": "Storage", "type": "percent_bar"},
        ],
    },

    # ... templates for every platform in every category
    # Each follows the same pattern: title, icon, list of typed metrics
}
```

### Metric Display Types

| Type | Rendering |
|------|-----------|
| `status` | Color-coded badge (green=online/healthy, yellow=degraded, red=offline/faulted) |
| `percent_bar` | Horizontal bar with color gradient (green < 70%, yellow < 85%, red > 85%) |
| `number` | Simple numeric display |
| `temperature` | Number with color (green < 50C, yellow < 70C, red > 70C) |
| `age` | Time since (e.g., "2h ago", "3 days ago") with color based on staleness |
| `bytes` | Human-readable size (e.g., "1.2 TB") |
| `throughput` | Bytes/sec with unit (e.g., "125 MB/s") |
| `list` | Compact list of items (e.g., drive names, VM names) |

### Generic Card Component

A single `IntegrationCard.vue` component renders ANY platform:

```vue
<!-- IntegrationCard.vue -->
<template>
  <DashboardCard :title="instance.id" :subtitle="template.title" :status="health">
    <div v-for="metric in template.metrics" :key="metric.key" class="metric-row">
      <span class="metric-label">{{ metric.label }}</span>
      <StatusBadge v-if="metric.type === 'status'" :value="data[metric.key]" />
      <PercentBar v-else-if="metric.type === 'percent_bar'" :value="data[metric.key]" />
      <TemperatureDisplay v-else-if="metric.type === 'temperature'" :value="data[metric.key]" />
      <AgeDisplay v-else-if="metric.type === 'age'" :value="data[metric.key]" />
      <span v-else>{{ data[metric.key] }}</span>
    </div>
  </DashboardCard>
</template>
```

### Dashboard Layout

Cards auto-populate based on configured integration instances:

- Each configured instance gets its own card
- Cards grouped by category (NAS, Hypervisor, Media, etc.)
- Operator can reorder, hide, or resize cards (preferences saved to localStorage)
- Multi-instance: 3 TrueNAS boxes = 3 separate cards with instance names as titles
- Offline instances show greyed-out card with "last seen" timestamp
- Click card -> drills into detail view with full metrics, heal history, dependency position

### Platform-Specific Detail Views

Clicking a card opens an expanded view with platform-specific detail:

- **NAS detail**: Pool list, disk list with SMART status, replication tasks, snapshot timeline, scrub history
- **Hypervisor detail**: VM list with status/resources, node cluster view, storage view, backup status
- **Media detail**: Library stats, active streams, transcode queue, recently added
- **DNS detail**: Query rate chart, blocked %, top blocked domains, upstream latency
- **Network detail**: Device list, client count, AP status, DHCP leases

### Adding New Platform Cards

To add a card for a new platform:
1. Add a `CARD_TEMPLATE` entry (Python dict)
2. Add a collector function that returns metrics matching the template keys
3. Register in integration_registry
4. Card renders automatically — no Vue component needed

For platforms with completely unique UIs (e.g., a dependency graph view for Kubernetes), a custom Vue component can override the template renderer while still using the same data pipeline.

---

## Section 15: Extended Integration Categories

### Additional Platforms Not Yet Listed

**Logging/SIEM** — Graylog, Grafana Loki, Elasticsearch/ELK/OpenSearch, Splunk, Fluentd/Fluent Bit, Seq, Logstash, rsyslog, Syslog-ng, Vector, Datadog Logs, Papertrail, Logtail

Abstract operations: `log_index_rotate`, `log_retention_enforce`, `log_pipeline_restart`, `log_forwarder_reconnect`, `log_alert_silence`, `log_query_cache_clear`, `log_ingestion_resume`

Card metrics: ingestion rate, storage used, index count, alert count, pipeline health

**Metrics/Time-Series** — Prometheus, InfluxDB, Graphite, TimescaleDB, VictoriaMetrics, Thanos, Mimir, Datadog

Abstract operations: `metrics_compaction`, `metrics_retention_enforce`, `metrics_scrape_restart`, `metrics_cardinality_prune`, `metrics_cache_clear`

Card metrics: series count, ingestion rate, storage used, scrape targets up/down, compaction status

**Message Queue/Streaming** — RabbitMQ, Kafka, Redis Streams, NATS, Mosquitto (MQTT), EMQX, ZeroMQ, ActiveMQ, Pulsar

Abstract operations: `queue_purge_dead_letters`, `queue_consumer_restart`, `queue_rebalance_partitions`, `queue_connection_reset`, `queue_dlq_replay`

Card metrics: queue depth, consumer count, message rate, dead letter count, connection count

**Container Orchestration** (expanded) — Kubernetes (K8s, K3s, MicroK8s), Docker Swarm, Nomad, Portainer, Rancher, OpenShift, Coolify, CapRover

Abstract operations: `k8s_pod_restart`, `k8s_deployment_rollback`, `k8s_drain_node`, `k8s_scale_deployment`, `k8s_clear_evicted`, `k8s_cordon_node`, `swarm_service_update`, `nomad_job_restart`

Card metrics: node count, pod count (running/pending/failed), deployment health, ingress status, PVC usage

**Wiki/Knowledge Base** (expanded) — Bookstack, Wiki.js, Outline, Notion (self-hosted proxy), Docmost, Trilium, Joplin Server, Standard Notes

Abstract operations: `wiki_reindex`, `wiki_cache_clear`, `wiki_backup_trigger`, `wiki_attachment_cleanup`

**Photo/Media Management** — Immich, PhotoPrism, Photoview, LibrePhotos, Lychee, Piwigo, Nextcloud Photos

Abstract operations: `photo_reindex`, `photo_thumbnail_regen`, `photo_ml_reprocess`, `photo_storage_optimize`, `photo_duplicate_scan`

Card metrics: photo/video count, storage used, ML job queue, import status

**Password/Secrets** (expanded) — Vaultwarden, HashiCorp Vault, Passbolt, Bitwarden (official), KeeWeb, Infisical, Doppler

Abstract operations: `vault_seal_check`, `vault_lease_revoke_expired`, `vault_audit_rotate`, `vault_cache_clear`, `vault_backup`

**Automation/Workflow** — n8n, Node-RED, Huginn, Automatisch, Activepieces, Windmill

Abstract operations: `workflow_restart_stuck`, `workflow_clear_queue`, `workflow_credential_refresh`, `workflow_execution_cleanup`

Card metrics: active workflows, execution count (24h), failed executions, queue depth

**Game Servers** — Pterodactyl, AMP, Crafty Controller, PufferPanel, LinuxGSM

Abstract operations: `game_server_restart`, `game_server_update`, `game_backup_trigger`, `game_mod_update`, `game_player_kick_idle`

Card metrics: server status, player count, TPS/tick rate, RAM usage, mod count

**LLM/AI** — Ollama, LocalAI, vLLM, Text Generation WebUI, LiteLLM, Open WebUI

Abstract operations: `llm_model_reload`, `llm_cache_clear`, `llm_queue_flush`, `llm_gpu_memory_release`, `llm_health_check`

Card metrics: loaded models, VRAM usage, requests/min, queue depth, GPU temp

**Recipes/Household** — Mealie, Tandoor, Grocy, Monica CRM, Homebox

Abstract operations: `app_cache_clear`, `app_db_optimize`, `app_reindex`

**File Sync** — Syncthing, Resilio Sync, Seafile, ownCloud, FileBrowser

Abstract operations: `sync_force_rescan`, `sync_conflict_resolve`, `sync_connection_reset`, `sync_index_rebuild`

Card metrics: sync status, folder count, conflict count, connected devices, transfer rate

**Status Page** (expanded) — Gatus, Cachet, Instatus, Upptime, StatPing, OneUptime

Abstract operations: `status_incident_auto_resolve`, `status_probe_restart`, `status_cache_refresh`

---

## Section 16: Configuration UI

(Renumbered from Section 14 — content follows)

### The Problem

NOBA currently has no UI for configuring:
- Integration instances (multi-instance with credentials)
- Dependency graphs
- Maintenance windows
- Heal action risk overrides
- Agent capability policies
- Integration groups
- Escalation chain definitions
- Approval timeouts and escalation rules
- Notification channel routing for healing
- Chaos test configuration

All healing config lives in `settings.yaml` which is edited manually. For a fully self-healing platform, operators need a UI to manage this without touching YAML files.

### New Settings Tabs

**1. Integrations Tab (new or extended)**

Current integrations config is basic (URL + token). Expand to:

- List all configured instances grouped by category
- Add/edit/remove instances with:
  - ID (unique name), platform (dropdown), URL, auth method
  - Site assignment, tags
  - Enable/disable toggle
  - Health status indicator (live probe)
  - "Test Connection" button
- Credential management via environment variable references
- Bulk import/export of integration config

**2. Healing Settings Tab (new)**

Sub-sections:

- **General**: Pipeline enable/disable, global heal cooldown, circuit breaker thresholds, stale data timeout
- **Risk Overrides**: Override default risk level for any action type (e.g., promote `container_recreate` from medium to high for specific targets)
- **Approval Policy**: Timeouts per stage, max defers, emergency override enable/disable per rule, confirmation cooldown duration
- **Notification Routing**: Channel assignment for heal events, digest settings, severity routing
- **Predictive Healing**: Enable/disable, evaluation interval, horizon thresholds, conservative/aggressive mode per category

**3. Dependencies Tab (new)**

- Visual dependency graph editor (drag-and-drop nodes, draw edges)
- Node type selector (external, infrastructure, service, agent)
- Health check configuration per node
- Site assignment
- Auto-discovered suggestions (accept/dismiss inline)
- Import/export dependency config

**4. Maintenance Tab (new)**

- Calendar view of all windows (scheduled + ad-hoc)
- Create new window: target selector (all / specific / group), cron expression builder, duration, action type
- Active windows with "end early" button
- History of past windows

**5. Escalation Chains Tab (within AlertsTab or standalone)**

- Visual chain builder: drag-and-drop action steps
- Per-step: action type, params, verify timeout, settle time
- Trust level assignment
- Preview: "If step 1 fails, step 2 runs, if step 2 fails..."

### Settings Storage

All configurable values follow the existing pattern:
- **Source of truth**: `settings.yaml` (YAML config on disk)
- **UI writes to YAML**: Settings API reads/writes the YAML file
- **Runtime cache**: Loaded into memory on startup, refreshed on config change
- **API**: Existing `/api/settings` pattern extended for new sections

Integration credentials are NEVER stored in YAML or DB. Only environment variable references are stored. The UI shows which env vars are configured and whether they resolve (without revealing the value).

---

## Success Criteria

1. **55+ heal actions** work cross-platform via capability dispatch with fallback chains
2. **24 integration categories** with abstract operations mapped to platform-specific handlers
3. **Multi-instance support** — multiple instances of the same platform with independent credentials, sites, and health tracking
4. **Instance groups** — bulk operations across groups of instances (e.g., all Pi-holes)
5. **Dependency graph** correctly identifies root cause and suppresses downstream healing
6. **ISP outage at one site** causes zero false heals at that site
7. **Agent-verified healing** prevents blind restarts when server can't confirm target state
8. **Tiered approvals** adapt to actual user base (single-admin, multi-admin, no-admin)
9. **Predictions** trigger conservative low-risk actions only
10. **Maintenance windows** correctly queue/suppress/evaluate heal events
11. **Rollback** restores pre-heal state for reversible actions
12. **Internal resilience** keeps NOBA functional when individual subsystems fail
13. **Chaos tests** validate all critical scenarios with reproducible results
14. **Dry-run** accurately simulates pipeline behavior without executing actions
15. **Dashboard** provides full visibility into healing effectiveness, dependencies, approvals
16. **Configuration UI** — full settings interface for integrations, dependencies, maintenance, escalation chains, approval policies
17. **Template-driven dashboard cards** — every configured integration instance auto-renders a card with platform-appropriate metrics
18. **35+ platform categories** — NAS, hypervisor, media, DNS, logging/SIEM, metrics, message queues, container orchestration, LLM/AI, game servers, file sync, and more
19. **Every action** has a complete audit trail regardless of risk/trust level
20. **Credential isolation** — each instance has independent auth, referenced via env vars only
21. **No edge case** from Section 13 causes unexpected behavior
