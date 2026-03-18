"""Noba – YAML configuration read/write helpers."""
from __future__ import annotations

import glob
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time

from .config import NOBA_YAML, WEB_KEYS, _NOTIF_WEB_KEYS

logger = logging.getLogger("noba")


def read_yaml_settings() -> dict:
    defaults: dict = {
        "piholeUrl": "", "piholeToken": "", "monitoredServices": "", "radarIps": "", "bookmarksStr": "",
        "plexUrl": "", "plexToken": "", "kumaUrl": "", "bmcMap": "", "backupSources": [], "backupDest": "",
        "cloudRemote": "", "downloadsDir": "", "truenasUrl": "", "truenasKey": "",
        "radarrUrl": "", "radarrKey": "", "sonarrUrl": "", "sonarrKey": "",
        "qbitUrl": "", "qbitUser": "", "qbitPass": "",
        "customActions": [], "automations": [], "wanTestIp": "8.8.8.8", "lanTestIp": "",
        "notifications": {}, "alertRules": [],
        "proxmoxUrl": "", "proxmoxUser": "", "proxmoxTokenName": "", "proxmoxTokenValue": "",
        "pushoverEnabled": False, "pushoverAppToken": "", "pushoverUserKey": "",
        "gotifyEnabled": False,   "gotifyUrl": "",        "gotifyAppToken": "",
    }
    if not os.path.exists(NOBA_YAML):
        return defaults
    try:
        r = subprocess.run(
            ["yq", "eval", "-o=json", ".", NOBA_YAML],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            full = json.loads(r.stdout)
            if isinstance(full, dict):
                web = full.get("web", {})
                for k in WEB_KEYS:
                    if k in web:
                        defaults[k] = web[k]
                backup = full.get("backup", {})
                if "sources" in backup: defaults["backupSources"] = backup["sources"]
                if "dest"    in backup: defaults["backupDest"]    = backup["dest"]
                cloud = full.get("cloud", {})
                if "remote" in cloud: defaults["cloudRemote"] = cloud["remote"]
                dl = full.get("downloads", {})
                if "dir" in dl: defaults["downloadsDir"] = dl["dir"]
                notif = full.get("notifications", {})
                if notif: defaults["notifications"] = notif
                push = notif.get("pushover", {})
                defaults["pushoverEnabled"]  = bool(push.get("enabled", False))
                defaults["pushoverAppToken"] = str(push.get("app_token", ""))
                defaults["pushoverUserKey"]  = str(push.get("user_key", ""))
                got = notif.get("gotify", {})
                defaults["gotifyEnabled"]  = bool(got.get("enabled", False))
                defaults["gotifyUrl"]      = str(got.get("url", ""))
                defaults["gotifyAppToken"] = str(got.get("app_token", ""))
                rules = web.get("alertRules", full.get("alertRules"))
                if rules is not None:
                    defaults["alertRules"] = rules
    except Exception as e:
        logger.warning("read_yaml_settings: %s", e)
    return defaults


def write_yaml_settings(settings: dict) -> bool:
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
            tmp.write("web:\n")
            for k, v in settings.items():
                if k not in WEB_KEYS or k in _NOTIF_WEB_KEYS:
                    continue
                tmp.write(f"  {k}: {json.dumps(v if isinstance(v, (str, list, dict)) else str(v))}\n")
            has_push = any(k in settings for k in ("pushoverEnabled", "pushoverAppToken", "pushoverUserKey"))
            has_got  = any(k in settings for k in ("gotifyEnabled", "gotifyUrl", "gotifyAppToken"))
            if has_push or has_got:
                tmp.write("notifications:\n")
                if has_push:
                    tmp.write("  pushover:\n")
                    tmp.write(f"    enabled: {json.dumps(bool(settings.get('pushoverEnabled', False)))}\n")
                    tmp.write(f"    app_token: {json.dumps(str(settings.get('pushoverAppToken', '')))}\n")
                    tmp.write(f"    user_key: {json.dumps(str(settings.get('pushoverUserKey', '')))}\n")
                if has_got:
                    tmp.write("  gotify:\n")
                    tmp.write(f"    enabled: {json.dumps(bool(settings.get('gotifyEnabled', False)))}\n")
                    tmp.write(f"    url: {json.dumps(str(settings.get('gotifyUrl', '')))}\n")
                    tmp.write(f"    app_token: {json.dumps(str(settings.get('gotifyAppToken', '')))}\n")
            tmp_path = tmp.name

        if os.path.exists(NOBA_YAML):
            backup = f"{NOBA_YAML}.bak.{int(time.time())}"
            try:
                shutil.copy2(NOBA_YAML, backup)
                for old in sorted(glob.glob(f"{NOBA_YAML}.bak.*"))[:-5]:
                    os.unlink(old)
            except Exception:
                pass
            r = subprocess.run(
                ["yq", "eval-all", "select(fileIndex==0) * select(fileIndex==1)", NOBA_YAML, tmp_path],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode != 0:
                raise RuntimeError(f"yq merge failed: {r.stderr.strip()}")
            with open(NOBA_YAML, "w") as f:
                f.write(r.stdout)
        else:
            os.makedirs(os.path.dirname(NOBA_YAML), exist_ok=True)
            with open(tmp_path) as src, open(NOBA_YAML, "w") as dst:
                dst.write(src.read())
        return True
    except Exception as e:
        logger.error("write_yaml_settings: %s", e)
        return False
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
