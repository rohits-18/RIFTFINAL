import os
import shutil
import logging
import json
import time
from backend.utils.models import AgentState
from backend.utils.paths import RESULTS_DIR, WORKSPACE_DIR

logger = logging.getLogger(__name__)

def run_healing_agent(repo_url: str, branch_name: str, run_id: str):
    """
    Orchestrator entrypoint:
    1. Prepares workspace
    2. Clones repository
    3. Triggers the LangGraph healing pipeline with progressive updates
    """
    try:
        from git import Repo
        from backend.orchestrator.graph import run_healing_pipeline
    except ImportError as e:
        logger.error(f"Environmental Error: Required dependencies (git/graph) not available: {e}")
        # Import internally to avoid another crash if it failed at top level
        from backend.orchestrator.main import _write_failure
        _write_failure(repo_url, branch_name, run_id, f"Engine Error: Backend environment is missing 'git' or pipeline dependencies. (Error: {e})")
        return

    logger.info(f"Starting agent run {run_id} for {repo_url} on {branch_name}")
    
    results_dir = RESULTS_DIR
    os.makedirs(results_dir, exist_ok=True)
    
    repo_dir = os.path.join(WORKSPACE_DIR, run_id)
    
    try:
        if os.path.exists(repo_dir):
            shutil.rmtree(repo_dir)
        os.makedirs(repo_dir, exist_ok=True)
        
        # We pass a callback to run_healing_pipeline to update the JSON progressively
        def update_callback(state: AgentState):
            _write_results(state)

        # 1. Create initial state with MISSION_INITIALIZED event
        from backend.utils.models import CITimelineEvent
        initial_state = AgentState(
            run_id=run_id,
            repo_url=repo_url,
            repo_path=repo_dir,
            branch_name=branch_name,
            start_time=time.time(),
            timeline=[
                CITimelineEvent(
                    iteration=0,
                    event_type="INITIALIZATION",
                    description=f"Mission initialized: Targeting {repo_url}"
                )
            ]
        )
        _write_results(initial_state)

        # 2. Start Cloning
        logger.info(f"Cloning {repo_url} to {repo_dir}...")
        initial_state.timeline.append(CITimelineEvent(
            iteration=0,
            event_type="CLONING",
            description=f"Cloning repository into isolated workspace..."
        ))
        _write_results(initial_state)
        
        if repo_url.startswith("/") or repo_url.startswith("file://"):
            source_path = repo_url.replace("file://", "")
            if os.path.exists(source_path):
                 shutil.copytree(source_path, repo_dir, dirs_exist_ok=True)
                 repo = Repo.init(repo_dir)
                 repo.git.add(A=True)
                 repo.index.commit("Initial local commit")
            else:
                 raise FileNotFoundError(f"Local repo path not found: {source_path}")
        else:
            repo = Repo.clone_from(repo_url, repo_dir)
        
        initial_state.timeline.append(CITimelineEvent(
            iteration=0,
            event_type="CLONING_COMPLETE",
            description=f"Repository clone successful. Launching LangGraph pipeline."
        ))
        _write_results(initial_state)

        final_state = run_healing_pipeline(
            repo_path=repo_dir,
            repo_url=repo_url,
            run_id=run_id,
            branch_name=branch_name,
            on_update=update_callback,
            initial_state=initial_state
        )

        _write_results(final_state)
        logger.info(f"Final results saved for {run_id}")

    except Exception as e:
        logger.error(f"Agent run failed: {e}")
        _write_failure(repo_url, branch_name, run_id, str(e))

def _write_results(state: AgentState):
    """Writes current AgentState to results.json for dashboard consumption."""
    status_mapped = state.ci_status
    if status_mapped == "SUCCESS":
        status_mapped = "RESOLVED"
    elif status_mapped == "RUNNING":
        status_mapped = "IN_PROGRESS"

    scoring_data = {
        "base_score": 100.0, "speed_factor": 0.0, "fix_efficiency": 0.0,
        "regression_penalty": 0.0, "final_ci_score": 0.0
    }
    if state.scoring:
        # Map backend model → dashboard contract
        base = getattr(state.scoring, 'base_score', 100.0)
        speed = getattr(state.scoring, 'speed_factor', 0.0)
        efficiency = getattr(state.scoring, 'fix_efficiency', 0.0)
        penalty = getattr(state.scoring, 'regression_penalty', 0.0)
        total = getattr(state.scoring, 'total_score', 0.0)
        scoring_data = {
            "base_score": base,
            "speed_factor": speed,
            "fix_efficiency": efficiency,
            "regression_penalty": penalty,
            "final_ci_score": total
        }

    fixes_data = []
    if state.fixes:
        for i, fix in enumerate(state.fixes):
            rel_path = fix.file_path
            repo_path_str = str(state.repo_path)
            if rel_path.startswith(repo_path_str):
                rel_path = os.path.relpath(rel_path, repo_path_str)
            
            # Clean up error type (remove Enum prefix)
            err_type = str(fix.failure_type).split('.')[-1]
            
            fixes_data.append({
                "file_path": rel_path,
                "error_type": err_type,
                "original_snippet": fix.original_code,
                "patched_snippet": fix.patched_code,
                "tests_passed": fix.validated,
                "line_number": getattr(fix, 'line_number', None),
                "commit_message": f"[AI-AGENT] Fix {err_type} in {os.path.basename(rel_path)}"
            })

    timeline_strings = []
    if hasattr(state, 'timeline') and state.timeline:
        for event in state.timeline:
            timeline_strings.append(event.description)

    # Compute elapsed time
    start_t = getattr(state, 'start_time', None) or time.time()
    elapsed = round(time.time() - start_t, 1)

    # Parse team/leader from branch name (TEAM_NAME_LEADER_NAME_AI_FIX)
    # RIFT_ORGANISERS_SAIYAM_KUMAR_AI_FIX -> Team: RIFT_ORGANISERS, Leader: SAIYAM_KUMAR
    branch_parts = state.branch_name.replace("_AI_FIX", "").split('_')
    mid = len(branch_parts) // 2
    team_name = "_".join(branch_parts[:mid]) if len(branch_parts) > 1 else branch_parts[0]
    leader_name = "_".join(branch_parts[mid:]) if len(branch_parts) > 1 else ""

    result_data = {
        "repo_url": state.repo_url,
        "branch_name": state.branch_name,
        "run_id": state.run_id,
        "total_failures": len(state.failures) if state.failures else 0,
        "total_fixes": len(fixes_data),
        "ci_status": status_mapped,
        "fixes": fixes_data,
        "ci_timeline": timeline_strings,
        "scoring": scoring_data,
        "iterations_used": getattr(state, 'iteration', 0),
        "max_retries": getattr(state, 'max_retries', 5),
        "start_time": start_t,
        "elapsed_seconds": elapsed,
        "team_name": team_name,
        "leader_name": leader_name
    }

    result_file = os.path.join(RESULTS_DIR, f"{state.run_id}.json")
    with open(result_file, 'w') as f:
        json.dump(result_data, f, indent=2)

def _write_failure(repo_url: str, branch_name: str, run_id: str, error_msg: str):
    result_file = os.path.join(RESULTS_DIR, f"{run_id}.json")
    failure_data = {
        "repo_url": repo_url,
        "branch_name": branch_name,
        "run_id": run_id,
        "total_failures": 0,
        "total_fixes": 0,
        "ci_status": "FAILED",
        "fixes": [],
        "ci_timeline": [f"Critical Error: {error_msg}"],
        "scoring": {
            "base_score": 0, "speed_factor": 0, "fix_efficiency": 0, 
            "regression_penalty": 0, "final_ci_score": 0
        }
    }
    with open(result_file, 'w') as f:
        json.dump(failure_data, f, indent=2)
