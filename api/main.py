import os
import uvicorn
import asyncio
import json
import time
import logging
import traceback
import requests
from uuid import uuid4
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from api.models import RunResult, RunAgentRequest
from backend.utils.paths import RESULTS_DIR

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Autonomous CI/CD Healing Core API")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global Exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"Internal Server Error: {str(exc)}",
            "traceback": traceback.format_exc(),
            "path": request.url.path
        }
    )

# Setup CORS
origins = [
    "http://localhost:5173", # Vite Default
    "http://localhost:3000", # React Create App Default
    "*", # Allow all for dev
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_repo_name(request: Request = None):
    """Smart repo detection for Vercel/GitHub."""
    # 1. Check Env
    env_repo = os.environ.get("GITHUB_REPOSITORY")
    if env_repo: return env_repo
    
    # 2. Check VERCEL Env Vars
    v_owner = os.environ.get("VERCEL_GIT_REPO_OWNER")
    v_slug = os.environ.get("VERCEL_GIT_REPO_SLUG")
    if v_owner and v_slug:
        return f"{v_owner}/{v_slug}"
    
    # 3. Check Host Header (Heuristic fallback)
    if request:
        try:
            host = request.headers.get("host", "")
            if "vercel.app" in host:
                parts = host.split('-')
                if len(parts) >= 3:
                     # e.g riftfinal-ident-owner.vercel.app -> slug=riftfinal, owner=owner
                     owner = parts[-1].split('.')[0]
                     slug = parts[0]
                     return f"{owner}/{slug}"
        except: pass
    
    return "rohits-18/RIFTFINAL"

def trigger_github_workflow(repo_url: str, branch_name: str, run_id: str, team_name: str, leader_name: str, request: Request = None):
    token = os.environ.get("GITHUB_TOKEN")
    if not token: return False, "GITHUB_TOKEN missing."
        
    repo_name = get_repo_name(request)
    url = f"https://api.github.com/repos/{repo_name}/actions/workflows/healing_agent.yml/dispatches"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Healing-Core"
    }
    
    data = {
        "ref": "main",
        "inputs": {
            "repo_url": repo_url, "branch_name": branch_name, "run_id": run_id,
            "team_name": team_name, "leader_name": leader_name
        }
    }
    
    try:
        logger.info(f"[v1.15] Triggering GHA in {repo_name} for run {run_id}")
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        if resp.status_code == 204:
            return True, None
        return False, f"GH Error {resp.status_code}: {resp.text}"
    except Exception as e:
        return False, str(e)

@app.get("/")
async def root():
    import shutil
    git_path = shutil.which("git")
    is_writable = os.access(RESULTS_DIR, os.W_OK)
    
    return {
        "status": "AI Core Online" if git_path else "AI Core DEGRADED (Git Missing)",
        "api_version": "1.15.0 PRO LIVE (Smart Discovery)",
        "git_available": bool(git_path),
        "environment": "Vercel" if os.environ.get("VERCEL") else "Regular",
        "is_writable": is_writable
    }

@app.get("/runs")
@app.get("/api/runs")
async def list_runs():
    try:
        runs = []
        if not os.path.exists(RESULTS_DIR): return []
        files = [(f, os.path.getmtime(os.path.join(RESULTS_DIR, f))) 
                 for f in os.listdir(RESULTS_DIR) if f.endswith(".json") and f != "results.json"]
        files.sort(key=lambda x: x[1], reverse=True)
        for filename, _ in files[:30]:
            try:
                with open(os.path.join(RESULTS_DIR, filename), 'r') as f:
                    data = json.load(f)
                    runs.append({
                        "run_id": data.get("run_id"),
                        "repo_url": data.get("repo_url"),
                        "ci_status": data.get("ci_status", "UNKNOWN"),
                        "total_fixes": data.get("total_fixes", 0)
                    })
            except: pass
        return runs
    except: return []

@app.post("/run-agent")
@app.post("/api/run-agent")
async def run_agent(request_data: RunAgentRequest, background_tasks: BackgroundTasks, request: Request):
    try:
        run_id = str(uuid4())
        branch_prefix = f"{request_data.team_name}_{request_data.leader_name}".upper().replace(" ", "_")
        expected_branch = f"{branch_prefix}_AI_FIX"
        
        if not os.path.exists(RESULTS_DIR): os.makedirs(RESULTS_DIR, exist_ok=True)

        initial_file = os.path.join(RESULTS_DIR, f"{run_id}.json")
        initial_data = {
            "repo_url": request_data.repo_url, "branch_name": expected_branch, "run_id": run_id,
            "total_failures": 0, "total_fixes": 0, "ci_status": "PENDING", "fixes": [],
            "ci_timeline": ["Mission initialized", "Spawning Cloud Core..."],
            "scoring": {"base_score": 100, "speed_factor": 0, "fix_efficiency": 0, "regression_penalty": 0, "final_ci_score": 0},
            "start_time": time.time(), "elapsed_seconds": 0,
            "team_name": request_data.team_name.upper(), "leader_name": request_data.leader_name.upper()
        }
        
        with open(initial_file, 'w') as f: json.dump(initial_data, f, indent=2)

        success, gha_error = trigger_github_workflow(
            request_data.repo_url, expected_branch, run_id, 
            request_data.team_name, request_data.leader_name, request
        )
        
        if not success:
            if os.environ.get("VERCEL"):
                raise HTTPException(status_code=500, detail=f"Live Healing failed to start. REASON: {gha_error}")
            else:
                from backend.orchestrator.main import run_healing_agent
                background_tasks.add_task(run_healing_agent, request_data.repo_url, expected_branch, run_id)
        
        return {
            "message": "Agent started (Cloud)" if success else "Agent started (Local)",
            "run_id": run_id, "branch_name": expected_branch, "execution_mode": "CLOUD" if success else "LOCAL"
        }
    except Exception as e:
        logger.error(f"Failed to start agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/results/{run_id}")
@app.get("/api/results/{run_id}")
async def get_results(run_id: str, request: Request):
    try:
        result_file_path = os.path.join(RESULTS_DIR, f"{run_id}.json")
        local_data = None
        
        if os.path.exists(result_file_path):
            try:
                with open(result_file_path, 'r') as f:
                    local_data = json.load(f)
            except: pass

        is_pending = not local_data or local_data.get("ci_status") == "PENDING"
        if is_pending:
            try:
                repo_name = get_repo_name(request)
                token = os.environ.get("GITHUB_TOKEN")
                headers = {"Accept": "application/vnd.github.v3.raw", "Cache-Control": "no-cache"}
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                    
                for branch in ["main", "master"]:
                    github_url = f"https://api.github.com/repos/{repo_name}/contents/backend/results/{run_id}.json?ref={branch}"
                    resp = requests.get(github_url, headers=headers, timeout=5)
                    if resp.status_code == 200:
                        return resp.json()
            except: pass

        if local_data:
            if local_data.get("ci_status") not in ("RESOLVED", "FAILED"):
                local_data["elapsed_seconds"] = round(time.time() - local_data.get("start_time", time.time()), 1)
            return local_data

        raise HTTPException(status_code=404, detail="Result not found yet.")
    except HTTPException as he: raise he
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Internal Error")

# Monitoring
from ci.github_monitor import get_workflow_logs, get_latest_workflow_run

@app.get("/ci/status")
async def get_ci_status(repo_url: str, branch_name: str):
    try:
        run = get_latest_workflow_run(repo_url, branch_name)
        return {"status": run.get("status"), "conclusion": run.get("conclusion"), "html_url": run.get("html_url")} if run else {"status": "UNKNOWN"}
    except: raise HTTPException(status_code=500)

@app.get("/ci/logs/{run_id}")
async def get_ci_logs(run_id: str, repo_url: str):
    try:
        logs = get_workflow_logs(repo_url, run_id)
        if not logs: raise HTTPException(status_code=404)
        return Response(content=logs, media_type="application/zip")
    except: raise HTTPException(status_code=500)

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
