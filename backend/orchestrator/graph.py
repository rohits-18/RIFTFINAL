"""
backend/orchestrator/graph.py
===============================
LangGraph Orchestrator — The master control graph for the CI/CD Healing Agent.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Literal

from langgraph.graph import END, START, StateGraph

from backend.agents.cicd_feedback_agent import CICDFeedbackAgent
from backend.agents.commit_optimizer_agent import CommitOptimizerAgent
from backend.agents.failure_classifier_agent import FailureClassifierAgent
from backend.agents.patch_generator_agent import PatchGeneratorAgent
from backend.agents.repo_analyzer_agent import RepoAnalyzerAgent
from backend.agents.root_cause_agent import RootCauseAgent
from backend.agents.scoring_agent import ScoringAgent
from backend.agents.test_runner_agent import TestRunnerAgent
from backend.agents.validation_agent import ValidationAgent
from backend.utils.logger import logger, setup_logger
from backend.utils.models import AgentState, CIStatus
from config.settings import settings


# ─────────────────────────────────────────────────────────────────────────────
# Node Functions (thin wrappers that call agents)
# ─────────────────────────────────────────────────────────────────────────────

def node_cicd_feedback(state: AgentState) -> AgentState:
    return CICDFeedbackAgent(state).run()

def node_repo_analyzer(state: AgentState) -> AgentState:
    return RepoAnalyzerAgent(state).run()

def node_test_runner(state: AgentState) -> AgentState:
    return TestRunnerAgent(state).run()

def node_failure_classifier(state: AgentState) -> AgentState:
    return FailureClassifierAgent(state).run()

def node_root_cause(state: AgentState) -> AgentState:
    return RootCauseAgent(state).run()

def node_patch_generator(state: AgentState) -> AgentState:
    return PatchGeneratorAgent(state).run()

def node_validation(state: AgentState) -> AgentState:
    return ValidationAgent(state).run()

def node_commit_optimizer(state: AgentState) -> AgentState:
    return CommitOptimizerAgent(state).run()

def node_scoring(state: AgentState) -> AgentState:
    return ScoringAgent(state).run()


# ─────────────────────────────────────────────────────────────────────────────
# Conditional Edge: Convergence Check
# ─────────────────────────────────────────────────────────────────────────────

def should_continue(state: AgentState) -> Literal["retry", "score"]:
    """
    Decision function after validation:
    - "score" if: no failures left, max retries hit, fatal error,
                  no tests exist + fixes applied, or no patches generated (LLM dead)
    - "retry" if: failures remain and retries available
    """
    if state.fatal_error:
        logger.error(f"[Orchestrator] Fatal error — stopping: {state.fatal_error}")
        return "score"

    remaining_failures = len([f for f in state.failures if not any(
        fix.failure_id == f.failure_id for fix in state.fixes
    )])

    if remaining_failures == 0:
        logger.success("[Orchestrator] All failures resolved — converging ✅")
        return "score"

    # ── New escape hatch #1 ────────────────────────────────────────────────────
    # If repo has NO tests (pytest exit_code=5) and we applied at least 1 fix,
    # stop — there's nothing to verify the remaining static-analysis warnings against.
    if getattr(state, "pytest_exit_code", None) == 5 and len(state.fixes) > 0:
        logger.success(
            f"[Orchestrator] No test suite + {len(state.fixes)} fix(es) applied — declaring RESOLVED ✅"
        )
        return "score"

    # ── New escape hatch #2 ────────────────────────────────────────────────────
    # If this iteration produced zero patches (LLM exhausted AND fallback also failed),
    # retrying won't help — stop now to avoid wasting max_retries cycles.
    if not state.patches and state.iteration > 0:
        logger.warning(
            "[Orchestrator] No patches generated this iteration (LLM+fallback both failed) — stopping"
        )
        return "score"

    if state.iteration >= state.max_retries:
        logger.warning(f"[Orchestrator] Max retries ({state.max_retries}) reached — stopping")
        return "score"

    # Prepare for retry
    state.iteration += 1
    # Reduce temperature adaptively
    new_temp = max(
        state.temperature_min,
        state.current_temperature * 0.75
    )
    logger.info(
        f"[Orchestrator] Retry {state.iteration}/{state.max_retries} | "
        f"remaining={remaining_failures} | temp={new_temp:.3f}"
    )
    state.current_temperature = new_temp
    return "retry"


# ─────────────────────────────────────────────────────────────────────────────
# Build Graph
# ─────────────────────────────────────────────────────────────────────────────

def build_healing_graph() -> StateGraph:
    """Construct the LangGraph state machine for autonomous CI healing."""

    builder = StateGraph(AgentState)

    # Register nodes
    builder.add_node("cicd_feedback",     node_cicd_feedback)
    builder.add_node("repo_analyzer",     node_repo_analyzer)
    builder.add_node("test_runner",       node_test_runner)
    builder.add_node("failure_classifier", node_failure_classifier)
    builder.add_node("root_cause",        node_root_cause)
    builder.add_node("patch_generator",   node_patch_generator)
    builder.add_node("validation",        node_validation)
    builder.add_node("commit_optimizer",  node_commit_optimizer)
    builder.add_node("scoring",           node_scoring)

    # Linear pipeline edges
    builder.add_edge(START,              "cicd_feedback")
    builder.add_edge("cicd_feedback",    "repo_analyzer")
    builder.add_edge("repo_analyzer",    "test_runner")
    builder.add_edge("test_runner",      "failure_classifier")
    builder.add_edge("failure_classifier", "root_cause")
    builder.add_edge("root_cause",       "patch_generator")
    builder.add_edge("patch_generator",  "validation")
    builder.add_edge("validation",       "commit_optimizer")

    # Conditional edge: retry or score
    builder.add_conditional_edges(
        "commit_optimizer",
        should_continue,
        {
            "retry": "test_runner",
            "score": "scoring",
        }
    )

    builder.add_edge("scoring", END)

    return builder.compile()


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def run_healing_pipeline(
    repo_path: str,
    repo_url: str,
    run_id: str,
    branch_name: str,
    ci_logs: str | None = None,
    on_update: Any = None
) -> AgentState:
    """
    Execute full healing pipeline with progressive updates.
    """
    from pathlib import Path
    log_dir = Path("backend/results") / run_id / "logs"
    setup_logger(run_id, log_dir)

    logger.info("=" * 70)
    logger.info("🚀 CI/CD Healing Intelligence Core — STARTING")
    logger.info("=" * 70)

    initial_state = AgentState(
        run_id=run_id,
        repo_url=repo_url,
        repo_path=repo_path,
        branch_name=branch_name,
        ci_logs=ci_logs,
        max_retries=settings.MAX_RETRIES,
        current_temperature=settings.OPENAI_TEMPERATURE_START,
        temperature_min=settings.OPENAI_TEMPERATURE_MIN,
        primary_model=settings.active_model,
        fallback_model="static-analysis-engine",
        fallback_triggered=False,
    )

    graph = build_healing_graph()
    final_state = initial_state

    try:
        # Stream the graph outputs
        for output in graph.stream(initial_state, config={"recursion_limit": 50}):
            # Each output is a dict: {node_name: state_dict}
            for node_name, state_dict in output.items():
                current_state = AgentState(**state_dict)
                final_state = current_state
                # Trigger callback for progressive dashboard updates
                if on_update:
                    on_update(current_state)
                    
    except Exception as e:
        logger.critical(f"[Orchestrator] Pipeline crashed: {e}")
        final_state.fatal_error = str(e)
        final_state.ci_status = CIStatus.FAILED
        if on_update:
            on_update(final_state)

    logger.info(f"🏁 Pipeline complete. Status: {final_state.ci_status}")
    return final_state
