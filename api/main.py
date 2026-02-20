import os
import uvicorn
import asyncio
import json
import time
import logging
from uuid import uuid4
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from api.models import RunResult, RunAgentRequest
from backend.utils.paths import RESULTS_DIR

from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
import logging
import traceback

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

# RESULTS_DIR is now imported from backend.utils.paths
logger.info(f"Using results directory: {RESULTS_DIR}")

@app.get("/")
async def root():
    is_writable = os.access(RESULTS_DIR, os.W_OK)
    return {
        "status": "AI Core Online",
        "version": "1.0.0",
        "results_dir": str(RESULTS_DIR),
        "is_writable": is_writable,
        "environment": "Vercel" if os.environ.get("VERCEL") else "Regular"
    }

@app.get("/runs")
@app.get("/api/runs")
async def list_runs():
    """List all recent runs, sorted by modification time."""
    try:
        runs = []
        if not os.path.exists(RESULTS_DIR):
            logger.warning(f"Results directory does not exist yet: {RESULTS_DIR}")
            return []
            
        files = []
        try:
            for filename in os.listdir(RESULTS_DIR):
                if filename.endswith(".json") and filename != "results.json":
                    file_path = os.path.join(RESULTS_DIR, filename)
                    files.append((filename, os.path.getmtime(file_path)))
        except Exception as dir_err:
            logger.error(f"Failed to list results directory: {dir_err}")
            return []
        
        files.sort(key=lambda x: x[1], reverse=True)
        
        for filename, _ in files[:30]: # Limit to 30 for history
            try:
                with open(os.path.join(RESULTS_DIR, filename), 'r') as f:
                    data = json.load(f)
                    runs.append({
                        "run_id": data.get("run_id"),
                        "repo_url": data.get("repo_url"),
                        "branch_name": data.get("branch_name"),
                        "ci_status": data.get("ci_status", "UNKNOWN"),
                        "total_fixes": data.get("total_fixes", 0)
                    })
            except Exception as e:
                logger.debug(f"Error reading {filename}: {e}")
        return runs
    except Exception as e:
        logger.error(f"Unexpected error in list_runs: {e}")
        return []

@app.post("/run-agent")
@app.post("/api/run-agent")
async def run_agent(request: RunAgentRequest, background_tasks: BackgroundTasks):
    try:
        # Generate Run ID
        run_id = str(uuid4())
        logger.info(f"Received run-agent request for {request.repo_url} (Run ID: {run_id})")
        
        # Consistent Branch Name logic
        branch_prefix = f"{request.team_name}_{request.leader_name}".upper().replace(" ", "_")
        expected_branch = f"{branch_prefix}_AI_FIX"
        
        # 1. Validation for filesystem
        if not os.path.exists(RESULTS_DIR):
            os.makedirs(RESULTS_DIR, exist_ok=True)

        if not os.access(RESULTS_DIR, os.W_OK):
             logger.error(f"RESULTS_DIR is not writable: {RESULTS_DIR}")
             raise HTTPException(status_code=500, detail=f"Filesystem Error: Missing write permissions for {RESULTS_DIR}")

        # 2. Write initial state
        initial_file = os.path.join(RESULTS_DIR, f"{run_id}.json")
        now = time.time()
        initial_data = {
            "repo_url": request.repo_url,
            "branch_name": expected_branch,
            "run_id": run_id,
            "total_failures": 0,
            "total_fixes": 0,
            "ci_status": "PENDING",
            "fixes": [],
            "ci_timeline": ["Mission initialized", "Status: PENDING — spawning orchestrator..."],
            "scoring": {
                "base_score": 100, "speed_factor": 0, "fix_efficiency": 0,
                "regression_penalty": 0, "final_ci_score": 0
            },
            "start_time": now,
            "elapsed_seconds": 0,
            "team_name": request.team_name.upper(),
            "leader_name": request.leader_name.upper(),
            "iterations_used": 0,
            "max_retries": 5
        }
        
        try:
            with open(initial_file, 'w') as f:
                json.dump(initial_data, f, indent=2)
        except Exception as write_err:
             logger.error(f"Failed to write initial state: {write_err}")
             raise HTTPException(status_code=500, detail=f"Filesystem Error: Could not save initial state to {RESULTS_DIR}")

        # 3. Trigger Background Task
        # Check if environment is correctly setup for cloning (token)
        if not os.environ.get("GITHUB_TOKEN"):
             logger.warning("GITHUB_TOKEN missing in environment! Push operations will fail.")

        from backend.orchestrator.main import run_healing_agent
        background_tasks.add_task(run_healing_agent, request.repo_url, expected_branch, run_id)
        
        return {
            "message": "Agent started",
            "run_id": run_id,
            "branch_name": expected_branch,
            "status": "QUEUED"
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Failed to start agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Startup Error: {str(e)}")

@app.get("/results/{run_id}")
@app.get("/api/results/{run_id}")
async def get_results(run_id: str):
    """Retrieve the results JSON for a specific run_id — returns raw dict."""
    try:
        result_file_path = os.path.join(RESULTS_DIR, f"{run_id}.json")

        if not os.path.exists(result_file_path):
            global_path = os.path.join(RESULTS_DIR, "results.json")
            if os.path.exists(global_path):
                with open(global_path, 'r') as f:
                    data = json.load(f)
                    if data.get("run_id") == run_id:
                        return data
            raise HTTPException(status_code=404, detail="Results not found yet. Agent might still be starting.")

        with open(result_file_path, 'r') as f:
            data = json.load(f)
            # Dynamically compute elapsed time while agent is still running
            import time as _time
            if data.get("start_time") and data.get("ci_status") not in ("RESOLVED", "FAILED"):
                data["elapsed_seconds"] = round(_time.time() - data["start_time"], 1)
            return data

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error retrieving results: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


# --- CI Monitoring Endpoints ---
from ci.github_monitor import get_workflow_logs, get_latest_workflow_run

@app.get("/ci/status")
async def get_ci_status(repo_url: str, branch_name: str):
    """
    Proxy to GitHub API to get the latest workflow run status for a branch.
    """
    try:
        run = get_latest_workflow_run(repo_url, branch_name)
        if not run:
            return {"status": "UNKNOWN", "details": "No workflow run found"}
        
        return {
            "status": run.get("status"), 
            "conclusion": run.get("conclusion"), 
            "html_url": run.get("html_url"),
            "run_id": run.get("id")
        }
    except Exception as e:
        logger.error(f"Error fetching CI status: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch CI status")

@app.get("/ci/logs/{run_id}")
async def get_ci_logs(run_id: str, repo_url: str):
    """
    Retrieve logs for a specific GitHub Actions run.
    """
    try:
        logs = get_workflow_logs(repo_url, run_id)
        if not logs:
             raise HTTPException(status_code=404, detail="Logs not found")
        
        # Return as plain text or zip/download? GitHub logs are zip.
        # For simplicity, we just return a message saying we can't stream zip easily without more logic, 
        # or we assume we extract it. 
        # The prompt says "capture failing logs". 
        # For now, let's just return a success signal or the raw content if small (it's binary).
        # Better to return a StreamingResponse.
        
        from fastapi.responses import Response
        return Response(content=logs, media_type="application/zip")
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error fetching logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch logs")

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
