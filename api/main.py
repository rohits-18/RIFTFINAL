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
from backend.orchestrator.main import run_healing_agent 
from backend.utils.paths import RESULTS_DIR

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Autonomous CI/CD Healing Core API")

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
    return {"status": "AI Core Online", "version": "1.0.0"}

@app.get("/runs")
async def list_runs():
    """List all recent runs, sorted by modification time."""
    try:
        runs = []
        files = []
        if not os.path.exists(RESULTS_DIR):
            logger.warning(f"Results dir not found: {RESULTS_DIR}")
            return []
            
        for filename in os.listdir(RESULTS_DIR):
            if filename.endswith(".json") and filename != "results.json":
                file_path = os.path.join(RESULTS_DIR, filename)
                files.append((filename, os.path.getmtime(file_path)))
        
        files.sort(key=lambda x: x[1], reverse=True)
        logger.info(f"Found {len(files)} run files in {RESULTS_DIR}")

        for filename, _ in files[:20]: # Limit to 20 for history
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
        logger.error(f"Error listing runs: {e}")
        return []

def _background_agent_runner(repo_url: str, branch_name: str, run_id: str):
    """Wrapper to run the sync agent function in a thread executor if needed, 
    but since it is sync, we can run it directly in background task or 
    wrap in run_in_executor to avoid blocking the event loop."""
    logger.info(f"Starting healing agent for {run_id} on branch {branch_name}")
    try:
        # The prompt says run_healing_agent is synchronous.
        # To avoid blocking the main thread, we should run it in an executor.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # However, FastAPI's BackgroundTasks run in a separate thread pool for sync functions automatically? 
        # Actually starlette/fastapi runs sync background tasks in a threadpool.
        run_healing_agent(repo_url, branch_name, run_id)
        logger.info(f"Healing agent completed for {run_id}")
    except Exception as e:
        logger.error(f"Error in background agent runner: {str(e)}")

@app.post("/run-agent")
async def run_agent(request: RunAgentRequest, background_tasks: BackgroundTasks):
    try:
        # Generate Run ID
        run_id = str(uuid4())
        
        # Validate Branch Name logic per prompt
        expected_branch = f"{request.team_name}_{request.leader_name}_AI_Fix".upper()
        if request.branch_name != expected_branch:
             pass

        # Write initial QUEUED state immediately to disk
        # This prevents 404 race conditions if background task is slow to start
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
            "leader_name": request.leader_name.upper()
        }
        with open(initial_file, 'w') as f:
            json.dump(initial_data, f, indent=2)

        # Trigger Background Task
        # FastAPI handles sync functions in background tasks by running them in a threadpool.
        background_tasks.add_task(run_healing_agent, request.repo_url, expected_branch, run_id)
        
        return {
            "message": "Agent started",
            "run_id": run_id,
            "branch_name": expected_branch,
            "status": "QUEUED"
        }
    except Exception as e:
        logger.error(f"Failed to start agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/results/{run_id}")
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
