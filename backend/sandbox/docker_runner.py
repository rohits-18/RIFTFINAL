"""
backend/sandbox/docker_runner.py
==================================
DockerRunner — Executes pytest inside an isolated Docker container,
mirroring the CI environment. Returns the same TestRunResult format.

The container:
- Uses python:3.11-slim base image
- Mounts repo as read-only
- Has a writeable /tmp for pytest reports
- Has resource limits (memory, CPU)
- Has a deterministic PYTHONHASHSEED=42
"""

from __future__ import annotations

import json
import os
import tarfile
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

from backend.agents.test_runner_agent import TestRunResult
from backend.utils.logger import logger
from config.settings import settings


class DockerRunner:
    """
    Isolated Docker-based test runner.
    Falls back to subprocess if Docker is unavailable.
    """

    PYTEST_SCRIPT = """
import subprocess, sys, json, os

result = subprocess.run(
    [sys.executable, '-m', 'pytest', '/repo',
     '--tb=short', '-q', '--no-header',
     '--json-report', '--json-report-file=/tmp/report.json',
     '--json-report-indent=2'],
    capture_output=True, text=True,
    env={**os.environ, 'PYTHONHASHSEED': '42'},
    timeout=110
)
print(result.stdout)
print(result.stderr, file=sys.stderr)
sys.exit(result.returncode)
"""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)
        self._client = None

    def _get_client(self):
        if self._client is None:
            import docker
            self._client = docker.from_env()
        return self._client

    def run_tests(self) -> TestRunResult:
        """Run pytest in Docker sandbox. Falls back to subprocess on error."""
        try:
            return self._run_in_docker()
        except Exception as e:
            logger.warning(f"[DockerRunner] Docker unavailable ({e}), falling back to subprocess")
            from backend.agents.test_runner_agent import TestRunnerAgent
            from backend.utils.models import AgentState

            # Minimal state for subprocess runner
            class _MinState:
                repo_path = str(self.repo_path)

            agent = TestRunnerAgent(_MinState())  # type: ignore
            return agent._execute_pytest()

    def _run_in_docker(self) -> TestRunResult:
        client = self._get_client()

        logger.info(f"[DockerRunner] Running tests in Docker container ({settings.SANDBOX_DOCKER_IMAGE})")
        t0 = time.time()

        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(self.PYTEST_SCRIPT.encode())
            script_path = f.name

        try:
            container = client.containers.run(
                image=settings.SANDBOX_DOCKER_IMAGE,
                command=f"python /tmp/run_tests.py",
                volumes={
                    str(self.repo_path): {"bind": "/repo", "mode": "ro"},
                    script_path: {"bind": "/tmp/run_tests.py", "mode": "ro"},
                },
                mem_limit=settings.SANDBOX_MEMORY_LIMIT,
                cpu_quota=settings.SANDBOX_CPU_QUOTA,
                environment={"PYTHONHASHSEED": "42"},
                detach=True,
                remove=False,
                network_disabled=False,  # allow pip installs if needed
            )

            exit_code = container.wait(timeout=settings.SANDBOX_TIMEOUT_SECONDS)["StatusCode"]
            logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")

            # Try to retrieve JSON report from container
            report: Dict[str, Any] = {}
            try:
                bits, _ = container.get_archive("/tmp/report.json")
                buf = BytesIO()
                for chunk in bits:
                    buf.write(chunk)
                buf.seek(0)
                with tarfile.open(fileobj=buf) as tf:
                    m = tf.extractfile("report.json")
                    if m:
                        report = json.loads(m.read().decode())
            except Exception:
                pass

            container.remove(force=True)
            elapsed = time.time() - t0

            summary = report.get("summary", {})
            return TestRunResult(
                exit_code=exit_code,
                total=summary.get("total", 0),
                passed=summary.get("passed", 0),
                failed=summary.get("failed", 0),
                errors=summary.get("error", 0),
                raw_output=logs,
                json_report=report,
                duration_seconds=elapsed,
            )

        finally:
            os.unlink(script_path)
