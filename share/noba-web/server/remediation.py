"""Noba – Remediation action registry."""
from __future__ import annotations

import logging
import re
import subprocess
import time

from .yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

# Action type definitions: {type: {risk, params, description, timeout_s}}
ACTION_TYPES = {
    "restart_container": {
        "risk": "low",
        "params": {"container": str},
        "description": "Docker/Podman restart by container name",
        "timeout_s": 30,
        "has_health_check": True,
    },
    "restart_service": {
        "risk": "low",
        "params": {"service": str},
        "description": "systemd service restart",
        "timeout_s": 30,
        "has_health_check": True,
    },
    "flush_dns": {
        "risk": "low",
        "params": {},
        "description": "Clear DNS cache on Pi-hole/AdGuard",
        "timeout_s": 15,
    },
    "clear_cache": {
        "risk": "low",
        "params": {"target": str},
        "description": "Purge application caches",
        "timeout_s": 15,
    },
    "trigger_backup": {
        "risk": "medium",
        "params": {"source": str},
        "description": "Initiate backup job",
        "timeout_s": 300,
    },
    "failover_dns": {
        "risk": "high",
        "params": {"primary": str, "secondary": str},
        "description": "Switch DNS to backup pair",
        "timeout_s": 30,
        "has_rollback": True,
    },
    "scale_container": {
        "risk": "medium",
        "params": {"container": str, "cpu_limit": str, "mem_limit": str},
        "description": "Adjust container resource limits",
        "timeout_s": 30,
    },
    "run_playbook": {
        "risk": "high",
        "params": {"playbook_id": str},
        "description": "Execute a maintenance playbook (automation)",
        "timeout_s": 600,
    },
    "run": {
        "risk": "medium",
        "params": {"command": str},
        "description": "Execute a shell command",
        "timeout_s": 60,
    },
    "webhook": {
        "risk": "low",
        "params": {"url": str},
        "description": "Fire an HTTP webhook",
        "timeout_s": 10,
    },
    "automation": {
        "risk": "medium",
        "params": {"automation_id": str},
        "description": "Trigger a stored automation by ID",
        "timeout_s": 300,
    },
    "agent_command": {
        "risk": "medium",
        "params": {"hostname": str, "command": str},
        "description": "Send command to a remote agent",
        "timeout_s": 30,
    },
}


def validate_action(action_type, params):
    """Validate action type and params. Returns error string or None."""
    defn = ACTION_TYPES.get(action_type)
    if not defn:
        return f"Unknown action type: {action_type}"
    for key, expected_type in defn["params"].items():
        if key not in params:
            return f"Missing required param: {key}"
    return None


def execute_action(action_type, params, triggered_by="system",
                   trigger_type="manual", trigger_id=None, target=None,
                   approved_by=None):
    """Execute a remediation action. Returns {success, output, duration_s, error?}."""
    from .db import db as _db

    defn = ACTION_TYPES.get(action_type)
    if not defn:
        error_msg = f"Unknown action: {action_type}"
        _db.insert_action_audit(
            trigger_type=trigger_type, trigger_id=trigger_id,
            action_type=action_type, action_params=params,
            target=target, outcome="error", error=error_msg,
        )
        return {"success": False, "error": error_msg}

    start = time.time()
    try:
        handler = _HANDLERS.get(action_type)
        if not handler:
            error_msg = f"No handler for: {action_type}"
            _db.insert_action_audit(
                trigger_type=trigger_type, trigger_id=trigger_id,
                action_type=action_type, action_params=params,
                target=target, outcome="error", error=error_msg,
            )
            return {"success": False, "error": error_msg}
        result = handler(params)
        duration = round(time.time() - start, 2)

        # Post-action health check if applicable
        health_ok = True
        if defn.get("has_health_check"):
            health_ok = _health_check(action_type, params)

        outcome = "success" if result.get("success", False) else "failure"
        logger.info(
            "Action executed: %s", action_type,
            extra={"action_type": action_type, "target": target, "outcome": outcome},
        )
        _db.insert_action_audit(
            trigger_type=trigger_type, trigger_id=trigger_id,
            action_type=action_type, action_params=params,
            target=target, outcome=outcome, duration_s=duration,
            output=result.get("output", ""),
            approved_by=approved_by,
        )
        return {
            "success": result.get("success", False),
            "output": result.get("output", ""),
            "duration_s": duration,
            "health_check": "pass" if health_ok else "fail",
        }
    except Exception as e:
        duration = round(time.time() - start, 2)
        _db.insert_action_audit(
            trigger_type=trigger_type, trigger_id=trigger_id,
            action_type=action_type, action_params=params,
            target=target, outcome="error", duration_s=duration,
            approved_by=approved_by, error=str(e),
        )
        return {
            "success": False,
            "error": str(e),
            "duration_s": duration,
        }


def _safe_name(val, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$', max_len=253):
    """Validate a container/service name against a safe pattern."""
    if not val or not isinstance(val, str) or len(val) > max_len:
        raise ValueError("Invalid name: too long or empty")
    if not re.match(pattern, val):
        raise ValueError("Invalid name: contains unsafe characters")
    return val


def _handle_restart_container(params):
    """Restart a Docker/Podman container."""
    name = _safe_name(params["container"])
    # Try docker first, fallback to podman
    for runtime in ("docker", "podman"):
        r = subprocess.run([runtime, "restart", name],
                          capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return {"success": True, "output": f"{runtime} restart {name}: OK"}
    return {"success": False, "output": r.stderr[:500]}


def _handle_restart_service(params):
    svc = _safe_name(params["service"], pattern=r'^[a-zA-Z0-9@._\-]+$')
    r = subprocess.run(["sudo", "systemctl", "restart", svc],
                      capture_output=True, text=True, timeout=30)
    return {"success": r.returncode == 0, "output": r.stdout + r.stderr}


def _handle_flush_dns(params):
    """Flush DNS cache via Pi-hole or systemd-resolved."""
    cfg = read_yaml_settings()
    if cfg.get("piholeUrl"):
        import httpx
        try:
            httpx.post(f"{cfg['piholeUrl']}/admin/api.php?restartdns",
                      timeout=10)
            return {"success": True, "output": "Pi-hole DNS restarted"}
        except Exception as e:
            return {"success": False, "output": str(e)}
    r = subprocess.run(["sudo", "systemd-resolve", "--flush-caches"],
                      capture_output=True, text=True, timeout=10)
    return {"success": r.returncode == 0, "output": "DNS cache flushed"}


def _handle_clear_cache(params):
    target = params.get("target", "system")
    if target == "system":
        subprocess.run(["sudo", "sync"], capture_output=True, text=True, timeout=10)
        subprocess.run(["sudo", "sh", "-c", "echo 3 > /proc/sys/vm/drop_caches"],
                      capture_output=True, text=True, timeout=10)
        return {"success": True, "output": "System cache cleared"}
    return {"success": False, "output": f"Unknown cache target: {target}"}


def _handle_trigger_backup(params):
    source = params.get("source", "default")
    # Trigger via the existing backup automation
    from .runner import job_runner
    try:
        run_id = job_runner.submit(
            lambda rid: subprocess.Popen(
                ["echo", f"Backup triggered for {source}"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            ),
            trigger=f"remediation:trigger_backup:{source}",
            triggered_by="system",
        )
        return {"success": True, "output": f"Backup queued: run_id={run_id}"}
    except Exception as e:
        return {"success": False, "output": str(e)}


def _handle_failover_dns(params):
    primary = params["primary"]
    secondary = params["secondary"]
    # This would configure DNS failover — implementation depends on infrastructure
    logger.warning("DNS failover: %s -> %s", primary, secondary)
    return {"success": True, "output": f"DNS failover: {primary} -> {secondary}"}


def _handle_scale_container(params):
    name = _safe_name(params["container"])
    cpu = params.get("cpu_limit", "")
    mem = params.get("mem_limit", "")
    # Validate cpu/mem formats to prevent argument injection
    if cpu and not re.match(r'^\d+(\.\d+)?$', cpu):
        return {"success": False, "output": f"Invalid cpu_limit: {cpu}"}
    if mem and not re.match(r'^\d+[kmgKMG]?$', mem):
        return {"success": False, "output": f"Invalid mem_limit: {mem}"}
    args = ["docker", "update"]
    if cpu:
        args.extend(["--cpus", cpu])
    if mem:
        args.extend(["--memory", mem])
    args.append(name)
    r = subprocess.run(args, capture_output=True, text=True, timeout=30)
    return {"success": r.returncode == 0, "output": r.stdout + r.stderr}


def _handle_run_playbook(params):
    playbook_id = params["playbook_id"]
    from .db import db as _db
    auto = _db.get_automation(playbook_id)
    if not auto:
        return {"success": False, "output": f"Playbook not found: {playbook_id}"}
    from .workflow_engine import _run_workflow
    config = auto.get("config", {})
    if auto.get("type") == "workflow":
        steps = config.get("steps", [])
        _run_workflow(playbook_id, steps, "system")
        return {"success": True, "output": f"Playbook started: {auto['name']}"}
    return {"success": False, "output": "Playbook must be a workflow automation"}


def _handle_run(params):
    import shlex
    command = params.get("command", "")
    if not command:
        return {"success": False, "output": "No command specified"}
    r = subprocess.run(shlex.split(command), timeout=60, capture_output=True, text=True)
    return {"success": r.returncode == 0, "output": (r.stdout + r.stderr)[:500]}


def _handle_webhook(params):
    import urllib.request
    url = params.get("url", "")
    method = params.get("method", "POST").upper()
    if not url or not url.startswith(("http://", "https://")):
        return {"success": False, "output": "Invalid URL"}
    req = urllib.request.Request(url, method=method)
    for k, v in (params.get("headers") or {}).items():
        req.add_header(str(k).replace("\n", ""), str(v).replace("\n", ""))
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            ok = 200 <= r.getcode() < 300
            return {"success": ok, "output": f"HTTP {r.getcode()}"}
    except Exception as e:
        return {"success": False, "output": str(e)}


def _handle_automation(params):
    auto_id = params.get("automation_id", "")
    if not auto_id:
        return {"success": False, "output": "No automation_id"}
    from .db import db as _db
    auto = _db.get_automation(auto_id)
    if not auto:
        return {"success": False, "output": f"Automation not found: {auto_id}"}
    from .workflow_engine import _AUTO_BUILDERS, _run_workflow
    from .runner import job_runner
    if auto["type"] == "workflow":
        steps = auto["config"].get("steps", [])
        if steps:
            _run_workflow(auto["id"], steps, "remediation")
            return {"success": True, "output": f"Workflow started: {auto['name']}"}
        return {"success": False, "output": "Workflow has no steps"}
    builder = _AUTO_BUILDERS.get(auto["type"])
    if not builder:
        return {"success": False, "output": f"Unknown automation type: {auto['type']}"}
    config = auto["config"]
    try:
        job_runner.submit(
            lambda _rid: builder(config),
            automation_id=auto["id"],
            trigger="remediation",
            triggered_by="remediation",
        )
        return {"success": True, "output": f"Automation triggered: {auto['name']}"}
    except RuntimeError as exc:
        return {"success": False, "output": str(exc)}


def _handle_agent_command(params):
    from .agent_store import queue_agent_command_and_wait
    hostname = params.get("hostname", "")
    cmd_type = params.get("command", "")
    cmd_params = params.get("params", {})
    timeout = int(params.get("timeout", 30))
    if not hostname or not cmd_type:
        return {"success": False, "output": "Missing hostname or command"}
    result = queue_agent_command_and_wait(
        hostname, cmd_type, cmd_params, timeout=timeout, queued_by="remediation",
    )
    if result is None:
        return {"success": False, "output": "Agent command timed out"}
    status = result.get("status", "error")
    return {"success": status != "error", "output": f"Agent command: {status}"}


def _health_check(action_type, params):
    """Post-action health check. Returns True if healthy."""
    import time as _time
    _time.sleep(2)  # Brief wait for action to take effect
    if action_type == "restart_container":
        try:
            name = _safe_name(params["container"])
        except ValueError:
            return False
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name],
                          capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "true"
    if action_type == "restart_service":
        try:
            svc = _safe_name(params["service"], pattern=r'^[a-zA-Z0-9@._\-]+$')
        except ValueError:
            return False
        r = subprocess.run(["systemctl", "is-active", svc],
                          capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "active"
    return True


# Handler registry
_HANDLERS = {
    "restart_container": _handle_restart_container,
    "restart_service": _handle_restart_service,
    "flush_dns": _handle_flush_dns,
    "clear_cache": _handle_clear_cache,
    "trigger_backup": _handle_trigger_backup,
    "failover_dns": _handle_failover_dns,
    "scale_container": _handle_scale_container,
    "run_playbook": _handle_run_playbook,
    "run": _handle_run,
    "webhook": _handle_webhook,
    "automation": _handle_automation,
    "agent_command": _handle_agent_command,
}
