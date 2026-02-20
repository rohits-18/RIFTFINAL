"""
main.py
========
Command-line entry point for the Autonomous CI/CD Healing Intelligence Core.

Usage:
    python main.py \\
        --repo-path /path/to/cloned/repo \\
        --repo-url  https://github.com/owner/repo \\
        --run-id    run-20240219-001 \\
        --branch    ai-healing-branch \\
        [--ci-logs  /path/to/actions.log]

AUTONOMY RULES enforced here:
- No interactive prompts
- No hardcoded paths
- All config from env/.env
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Autonomous CI/CD Healing Intelligence Core",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --repo-path ./my-repo --repo-url https://github.com/org/repo

  python main.py \\
    --repo-path ./my-repo \\
    --repo-url  https://github.com/org/repo \\
    --run-id    run-abc123 \\
    --branch    ai-healing \\
    --ci-logs   ./actions.log
        """,
    )
    parser.add_argument(
        "--repo-path",
        required=True,
        help="Absolute or relative path to the locally cloned repository",
    )
    parser.add_argument(
        "--repo-url",
        required=True,
        help="Remote GitHub URL of the repository (used in results.json)",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Unique run identifier. Auto-generated if not provided.",
    )
    parser.add_argument(
        "--branch",
        default="ai-healing",
        help="Git branch name for AI fixes (default: ai-healing)",
    )
    parser.add_argument(
        "--ci-logs",
        default=None,
        help="Path to raw GitHub Actions log file (optional)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Validate repo path
    repo_path = Path(args.repo_path).resolve()
    if not repo_path.exists():
        print(f"[ERROR] Repo path does not exist: {repo_path}", file=sys.stderr)
        return 1

    # Auto-generate run_id if not provided
    run_id = args.run_id or f"run-{uuid.uuid4().hex[:12]}"

    # Load CI logs if provided
    ci_logs: str | None = None
    if args.ci_logs:
        ci_log_path = Path(args.ci_logs)
        if ci_log_path.exists():
            ci_logs = ci_log_path.read_text(encoding="utf-8", errors="replace")
        else:
            print(f"[WARN] CI logs file not found: {ci_log_path}", file=sys.stderr)

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║     🧠 Autonomous CI/CD Healing Intelligence Core            ║
║     Production Grade — LangGraph + GPT-4o                   ║
╠══════════════════════════════════════════════════════════════╣
║  run_id   : {run_id:<50}║
║  repo     : {str(repo_path):<50}║
║  branch   : {args.branch:<50}║
╚══════════════════════════════════════════════════════════════╝
    """)

    # Run the pipeline
    from backend.orchestrator.graph import run_healing_pipeline

    final_state = run_healing_pipeline(
        repo_path=str(repo_path),
        repo_url=args.repo_url,
        run_id=run_id,
        branch_name=args.branch,
        ci_logs=ci_logs,
    )

    from backend.utils.models import AgentState

    # LangGraph may return a plain dict — convert back to AgentState
    if isinstance(final_state, dict):
        final_state = AgentState(**final_state)

    # Write results.json
    from backend.orchestrator.main import _write_results
    _write_results(final_state)

    print(f"\n✅ Results written to backend/results/{run_id}.json")
    print(f"   CI Status : {final_state.ci_status}")
    print(f"   Failures  : {len(final_state.failures)}")
    print(f"   Fixes     : {len(final_state.fixes)}")
    if final_state.scoring:
        print(f"   Score     : {final_state.scoring.total_score:.2f}")

    return 0 if final_state.ci_status in ("SUCCESS", "PARTIAL", "RESOLVED") else 1


if __name__ == "__main__":
    sys.exit(main())
