# share/noba-web/server/routers/api.py
import subprocess
import os
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from ..metrics import get_system_metrics
from ..database import db
from ..security import verify_token
from ..config import settings

# Every route in this file requires a valid JWT Bearer token
router = APIRouter(dependencies=[Depends(verify_token)])

@router.get("/metrics/live")
async def live_metrics(background_tasks: BackgroundTasks):
    """Returns sub-millisecond telemetry and logs to SQLite in the background."""
    data = get_system_metrics()

    # Offload the database disk I/O to a background thread so the HTTP response is instant
    background_tasks.add_task(db.insert_metrics, data)
    return data

@router.post("/action/{command}")
async def trigger_action(command: str):
    """Safely triggers an automation script. Completely immune to command injection."""
    if command not in settings.automation.allowed_commands:
        raise HTTPException(
            status_code=403,
            detail=f"Command '{command}' is not in the allowed_commands config."
        )

    script_path = os.path.expanduser(f"~/.local/libexec/noba/{command}.sh")
    if not os.path.exists(script_path):
        raise HTTPException(status_code=404, detail="Automation script not found on disk.")

    try:
        # Popen runs the script asynchronously so the web UI doesn't hang waiting for it
        subprocess.Popen([script_path])
        return {"status": "success", "detail": f"Automation triggered: {command}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
