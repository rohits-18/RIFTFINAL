"""
backend/agents/test_runner_agent.py
=====================================
TestRunnerAgent — Universal Polyglot Test Dispatcher.

Detects the language mode from AgentState and runs:
  PYTHON   → pytest  (with JSON report)
  NODE_JS  → npm test / yarn test  (parses TAP / jest-json)
  JAVA     → mvn test / gradle test  (parses Surefire XML / stdout)

All runners produce a normalised TestRunResult so the rest of the
pipeline remains language-agnostic.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.utils.logger import logger
from backend.utils.models import AgentState, CITimelineEvent, LanguageMode


# ─────────────────────────────────────────────────────────────────────────────
# Normalised result (language-agnostic)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TestRunResult:
    exit_code: int
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    warnings: int = 0
    raw_output: str = ""
    json_report: Dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0
    stack_traces: List[str] = field(default_factory=list)
    runner_used: str = "pytest"


# ─────────────────────────────────────────────────────────────────────────────
# TestRunnerAgent
# ─────────────────────────────────────────────────────────────────────────────

class TestRunnerAgent:
    """
    Executes the correct test suite for the detected repository language and
    normalises the output into a standard TestRunResult.
    """

    PYTEST_JSON_FILE = ".pytest_report.json"

    def __init__(self, state: AgentState):
        self.state = state
        self.repo_path = Path(state.repo_path)
        self.language = getattr(state, "repo_language", LanguageMode.PYTHON)
        self.tool = getattr(state, "test_runner_tool", "pytest")

    # ─────────────────────────────────────────
    def run(self) -> AgentState:
        t0 = time.time()
        logger.info(
            f"[TestRunnerAgent] Running tests — language={self.language}, tool={self.tool}"
        )

        if self.language == LanguageMode.NODE_JS:
            result = self._execute_node()
        elif self.language == LanguageMode.JAVA:
            result = self._execute_java()
        else:
            result = self._execute_pytest()

        elapsed = time.time() - t0

        self.state.timeline.append(CITimelineEvent(
            iteration=self.state.iteration,
            event_type="TEST_RUN",
            description=(
                f"[{result.runner_used}] exit_code={result.exit_code} | "
                f"total={result.total} passed={result.passed} "
                f"failed={result.failed} errors={result.errors}"
            ),
            failures_before=result.failed + result.errors,
            duration_seconds=elapsed,
        ))

        # Persist into state fields (language-agnostic names)
        self.state.pytest_output    = result.raw_output       # generic "test output"
        self.state.pytest_json_report = result.json_report
        self.state.pytest_exit_code = result.exit_code
        self.state.pytest_pass_count = result.passed
        self.state.pytest_fail_count = result.failed

        logger.info(
            f"[TestRunnerAgent] Done in {elapsed:.2f}s | "
            f"exit={result.exit_code} pass={result.passed} fail={result.failed}"
        )
        return self.state

    # ═══════════════════════════════════════════
    # PYTHON — pytest
    # ═══════════════════════════════════════════

    def _execute_pytest(self) -> TestRunResult:
        json_report_path = self.PYTEST_JSON_FILE
        cmd = [
            sys.executable, "-m", "pytest",
            "-n", "auto", # Parallel execution via pytest-xdist
            "--tb=short", "--no-header", "-q",
            "--json-report",
            f"--json-report-file={json_report_path}",
        ]

        env = {**os.environ,
               "PYTHONDONTWRITEBYTECODE": "1",
               "PYTHONUNBUFFERED": "1",
               "PYTHONHASHSEED": "42"}

        t0 = time.time()
        try:
            logger.info(f"[TestRunnerAgent] Running pytest in {self.repo_path}")
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=120, cwd=str(self.repo_path), env=env,
            )

            raw = proc.stdout + "\n" + proc.stderr
            report: Dict[str, Any] = {}
            full_report = self.repo_path / json_report_path
            if full_report.exists():
                try:
                    report = json.loads(full_report.read_text())
                except Exception as e:
                    logger.warning(f"[TestRunnerAgent] Corrupt JSON report: {e}")

            summary = report.get("summary", {})
            stack_traces = [
                t.get("call", {}).get("longrepr", "")
                for t in report.get("tests", [])
                if t.get("outcome") in ("failed", "error")
            ]

            return TestRunResult(
                exit_code=proc.returncode,
                total=summary.get("total", 0),
                passed=summary.get("passed", 0),
                failed=summary.get("failed", 0),
                errors=summary.get("error", 0),
                warnings=summary.get("warnings", 0),
                raw_output=raw,
                json_report=report,
                duration_seconds=time.time() - t0,
                stack_traces=stack_traces,
                runner_used="pytest",
            )

        except subprocess.TimeoutExpired:
            logger.error("[TestRunnerAgent] pytest timed out after 120s")
            return TestRunResult(exit_code=-1, raw_output="TIMEOUT", runner_used="pytest")
        except FileNotFoundError:
            logger.error("[TestRunnerAgent] pytest not found")
            return TestRunResult(exit_code=-127, raw_output="pytest not found", runner_used="pytest")
        except Exception as e:
            logger.error(f"[TestRunnerAgent] pytest error: {e}")
            return TestRunResult(exit_code=-2, raw_output=str(e), runner_used="pytest")

    # ═══════════════════════════════════════════
    # NODE.JS — npm test / yarn test
    # ═══════════════════════════════════════════

    def _execute_node(self) -> TestRunResult:
        """
        Runs `npm test` or `yarn test`.
        Attempts to parse Jest's JSON output if --json flag is supported,
        otherwise falls back to text parsing.
        """
        use_yarn = self.tool.startswith("yarn")
        runner = "yarn" if use_yarn else "npm"

        # Try with Jest JSON reporter first
        jest_json_path = self.repo_path / ".jest_results.json"
        cmd_json = [runner, "test", "--", "--json",
                    f"--outputFile={jest_json_path}", "--forceExit", "--passWithNoTests"]
        cmd_plain = [runner, "test", "--", "--forceExit", "--passWithNoTests"]

        env = {**os.environ, "CI": "true", "NODE_ENV": "test"}
        t0 = time.time()

        try:
            logger.info(f"[TestRunnerAgent] Running {' '.join(cmd_json)} in {self.repo_path}")
            proc = subprocess.run(
                cmd_json, capture_output=True, text=True,
                timeout=180, cwd=str(self.repo_path), env=env,
            )

            raw = proc.stdout + "\n" + proc.stderr

            # Try to parse Jest JSON output file
            if jest_json_path.exists():
                try:
                    report = json.loads(jest_json_path.read_text())
                    return self._parse_jest_json(report, raw, proc.returncode, time.time() - t0)
                except Exception as e:
                    logger.warning(f"[TestRunnerAgent] Jest JSON parse failed: {e}")

            # Fallback: parse text output
            return self._parse_node_text(raw, proc.returncode, time.time() - t0, runner)

        except subprocess.TimeoutExpired:
            logger.error(f"[TestRunnerAgent] {runner} test timed out after 180s")
            return TestRunResult(exit_code=-1, raw_output="TIMEOUT", runner_used=runner)
        except FileNotFoundError:
            logger.error(f"[TestRunnerAgent] {runner} not found — is Node.js installed?")
            return TestRunResult(exit_code=-127, raw_output=f"{runner} not found", runner_used=runner)
        except Exception as e:
            logger.error(f"[TestRunnerAgent] Node test error: {e}")
            return TestRunResult(exit_code=-2, raw_output=str(e), runner_used=runner)

    def _parse_jest_json(
        self, report: Dict[str, Any], raw: str, exit_code: int, elapsed: float
    ) -> TestRunResult:
        num_passed = report.get("numPassedTests", 0)
        num_failed = report.get("numFailedTests", 0)
        num_pending = report.get("numPendingTests", 0)
        num_total = report.get("numTotalTests", num_passed + num_failed + num_pending)

        stack_traces: List[str] = []
        for suite in report.get("testResults", []):
            for result in suite.get("testResults", []):
                if result.get("status") == "failed":
                    for msg in result.get("failureMessages", []):
                        stack_traces.append(msg)

        return TestRunResult(
            exit_code=exit_code,
            total=num_total,
            passed=num_passed,
            failed=num_failed,
            errors=0,
            warnings=0,
            raw_output=raw,
            json_report=report,
            duration_seconds=elapsed,
            stack_traces=stack_traces,
            runner_used="jest",
        )

    def _parse_node_text(
        self, raw: str, exit_code: int, elapsed: float, runner: str
    ) -> TestRunResult:
        """
        Parse plain text output from mocha / jest / vitest / tap.
        Extracts pass/fail counts via regex heuristics.
        """
        passed = failed = total = 0

        # Jest text: "Tests: 3 failed, 5 passed, 8 total"
        jest_m = re.search(
            r"Tests:\s+(?:(\d+) failed,\s*)?(?:(\d+) passed,\s*)?(\d+) total", raw, re.I
        )
        if jest_m:
            failed  = int(jest_m.group(1) or 0)
            passed  = int(jest_m.group(2) or 0)
            total   = int(jest_m.group(3) or 0)

        # Mocha text: "5 passing  2 failing"
        mocha_pass = re.search(r"(\d+)\s+passing", raw, re.I)
        mocha_fail = re.search(r"(\d+)\s+failing", raw, re.I)
        if mocha_pass or mocha_fail:
            passed  = int(mocha_pass.group(1)) if mocha_pass else 0
            failed  = int(mocha_fail.group(1)) if mocha_fail else 0
            total   = passed + failed

        # Vitest / tap: "✓ 5 | ✗ 2"
        vitest_m = re.search(r"✓\s*(\d+)\s*\|?\s*✗\s*(\d+)", raw)
        if vitest_m:
            passed, failed = int(vitest_m.group(1)), int(vitest_m.group(2))
            total = passed + failed

        stack_traces = re.findall(r"(?:Error|FAIL):?\s+(.+)", raw)

        return TestRunResult(
            exit_code=exit_code,
            total=total,
            passed=passed,
            failed=failed,
            errors=0,
            raw_output=raw,
            json_report={},
            duration_seconds=elapsed,
            stack_traces=stack_traces,
            runner_used=runner,
        )

    # ═══════════════════════════════════════════
    # JAVA — mvn test / gradle test
    # ═══════════════════════════════════════════

    def _execute_java(self) -> TestRunResult:
        """
        Runs `mvn test` or `gradle test` and parses Surefire/Failsafe XML reports.
        Falls back to text parsing if XML not found.
        """
        use_gradle = self.tool.startswith("gradle")
        if use_gradle:
            # Use gradlew wrapper if present
            gradlew = self.repo_path / "gradlew"
            cmd = [str(gradlew) if gradlew.exists() else "gradle", "test", "--info"]
        else:
            mvnw = self.repo_path / "mvnw"
            cmd = [str(mvnw) if mvnw.exists() else "mvn", "test", "-B", "--no-transfer-progress"]

        env = {**os.environ, "JAVA_HOME": os.environ.get("JAVA_HOME", ""),
               "MAVEN_OPTS": "-Xmx512m"}
        t0 = time.time()

        try:
            logger.info(f"[TestRunnerAgent] Running {' '.join(cmd)} in {self.repo_path}")
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=300, cwd=str(self.repo_path), env=env,
            )

            raw = proc.stdout + "\n" + proc.stderr
            elapsed = time.time() - t0

            # Try Surefire XML reports
            result = self._parse_surefire_xml(raw, proc.returncode, elapsed)
            if result is not None:
                return result

            # Fallback: parse Maven/Gradle text output
            return self._parse_java_text(raw, proc.returncode, elapsed,
                                          "gradle" if use_gradle else "mvn")

        except subprocess.TimeoutExpired:
            logger.error("[TestRunnerAgent] Java test timed out after 300s")
            return TestRunResult(exit_code=-1, raw_output="TIMEOUT", runner_used="mvn")
        except FileNotFoundError:
            logger.error("[TestRunnerAgent] mvn/gradle not found")
            return TestRunResult(exit_code=-127, raw_output="mvn/gradle not found", runner_used="mvn")
        except Exception as e:
            logger.error(f"[TestRunnerAgent] Java test error: {e}")
            return TestRunResult(exit_code=-2, raw_output=str(e), runner_used="mvn")

    def _parse_surefire_xml(
        self, raw: str, exit_code: int, elapsed: float
    ) -> Optional[TestRunResult]:
        """Parse Maven Surefire XML reports from target/surefire-reports/."""
        xml_dirs = list(self.repo_path.rglob("surefire-reports"))
        if not xml_dirs:
            return None

        total = passed = failed = errors = 0
        stack_traces: List[str] = []

        for xml_dir in xml_dirs:
            for xml_file in xml_dir.glob("*.xml"):
                try:
                    tree = ET.parse(xml_file)
                    root = tree.getroot()
                    total   += int(root.get("tests",    0))
                    failed  += int(root.get("failures", 0))
                    errors  += int(root.get("errors",   0))
                    for failure in root.iter("failure"):
                        stack_traces.append(failure.text or "")
                    for error in root.iter("error"):
                        stack_traces.append(error.text or "")
                except ET.ParseError:
                    continue

        passed = total - failed - errors

        return TestRunResult(
            exit_code=exit_code,
            total=total,
            passed=passed,
            failed=failed,
            errors=errors,
            raw_output=raw,
            duration_seconds=elapsed,
            stack_traces=stack_traces,
            runner_used="mvn",
        )

    def _parse_java_text(
        self, raw: str, exit_code: int, elapsed: float, runner: str
    ) -> TestRunResult:
        """
        Parse plain Maven/Gradle output.
        Maven: "Tests run: 10, Failures: 2, Errors: 0, Skipped: 1"
        Gradle: "5 tests completed, 2 failed"
        """
        total = passed = failed = errors = 0

        # Maven aggregate line
        maven_m = re.search(
            r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+)", raw, re.I
        )
        if maven_m:
            total  = int(maven_m.group(1))
            failed = int(maven_m.group(2))
            errors = int(maven_m.group(3))
            passed = total - failed - errors

        # Gradle summary line
        gradle_m = re.search(r"(\d+) tests? completed(?:,\s*(\d+) failed)?", raw, re.I)
        if gradle_m:
            total  = int(gradle_m.group(1))
            failed = int(gradle_m.group(2) or 0)
            passed = total - failed

        stack_traces = re.findall(r"(?:FAILED|ERROR):\s+(.+)", raw)

        return TestRunResult(
            exit_code=exit_code,
            total=total,
            passed=passed,
            failed=failed,
            errors=errors,
            raw_output=raw,
            duration_seconds=elapsed,
            stack_traces=stack_traces,
            runner_used=runner,
        )

    # ─────────────────────────────────────────
    # Convenience: single test run (validation re-run)
    # ─────────────────────────────────────────
    def run_single_test(self, test_id: str) -> TestRunResult:
        """Run a single test by ID (Python only for now)."""
        cmd = [sys.executable, "-m", "pytest", test_id, "--tb=short", "-q", "--no-header"]
        t0 = time.time()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=60, cwd=str(self.repo_path),
                env={**os.environ, "PYTHONHASHSEED": "42"},
            )
        except subprocess.TimeoutExpired:
            return TestRunResult(exit_code=-1, runner_used="pytest")
        return TestRunResult(
            exit_code=proc.returncode,
            raw_output=proc.stdout + proc.stderr,
            duration_seconds=time.time() - t0,
            runner_used="pytest",
        )
