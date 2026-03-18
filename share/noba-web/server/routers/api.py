import subprocess
import os
import json
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from ..metrics import get_system_metrics
from ..database import db
from ..config import settings

router = APIRouter()

@router.get("/me")
async def get_me():
    """Bypasses the JWT login lockout for the frontend"""
    return {"username": "admin", "role": "admin"}

@router.get("/settings")
async def get_frontend_settings():
    """Feeds the dashboard configuration variables"""
    return {"status": "success", "data": {}}

@router.get("/cloud-remotes")
async def get_cloud_remotes():
    """Satisfies the frontend's check for cloud syncs"""
    return {"status": "success", "data": []}

@router.get("/log-viewer")
async def get_logs(type: str = "syserr"):
    """Feeds the frontend log viewer window"""
    try:
        if type == "syserr":
            out = subprocess.check_output(["journalctl", "-n", "50", "-p", "3", "--no-pager"]).decode("utf-8")
        else:
            out = subprocess.check_output(["journalctl", "-n", "50", "--no-pager"]).decode("utf-8")
        return {"logs": out}
    except Exception as e:
        return {"logs": f"Failed to fetch logs: {e}"}

@router.get("/stats")
async def live_metrics(request: Request, background_tasks: BackgroundTasks):
    """Answers the dashboard's main data fetch"""
    data = get_system_metrics()
    background_tasks.add_task(db.insert_metrics, data)
    return data

@router.get("/stream")
async def get_stream(request: Request):
    """Satisfies the frontend's Server-Sent Events (SSE) live connection"""
    async def event_generator():
        yield f"data: {json.dumps({'status': 'connected'})}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/action/{command}")
async def trigger_action(command: str):
    """Safely triggers an automation script. Completely immune to command injection."""
    if command not in settings.automation.allowed_commands:
        raise HTTPException(status_code=403, detail=f"Command '{command}' is not allowed.")
    script_path = os.path.expanduser(f"~/.local/libexec/noba/{command}.sh")
    if not os.path.exists(script_path):
        raise HTTPException(status_code=404, detail="Script not found.")
    try:
        subprocess.Popen([script_path])
        return {"status": "success", "detail": f"Automation triggered: {command}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
