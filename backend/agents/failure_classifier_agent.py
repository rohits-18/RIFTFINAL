"""
backend/agents/failure_classifier_agent.py
============================================
FailureClassifierAgent — Classifies raw pytest output + AST issues
into structured Failure objects with type, severity, file, line, message.
Uses AST + regex — NO LLM call in the classification phase.
"""

from __future__ import annotations

import os
import json
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple

from backend.agents.test_runner_agent import TestRunResult
from backend.utils.ast_parser import ASTParser
from backend.utils.logger import logger
from backend.utils.models import (
    AgentState,
    CITimelineEvent,
    Failure,
    FailureType,
    LanguageMode,
    Severity,
)


# ─────────────────────────────────────────────────────────────────────────────
# Stack trace patterns
# ─────────────────────────────────────────────────────────────────────────────

PATTERNS = {
    FailureType.SYNTAX: [
        re.compile(r"SyntaxError: (.+)", re.I),
        re.compile(r"IndentationError: (.+)", re.I),
    ],
    FailureType.IMPORT: [
        re.compile(r"ModuleNotFoundError: No module named ['\"](.+?)['\"]", re.I),
        re.compile(r"ImportError: (.+)", re.I),
        re.compile(r"cannot import name ['\"](.+?)['\"]", re.I),
    ],
    FailureType.TYPE_ERROR: [
        re.compile(r"TypeError: (.+)", re.I),
    ],
    FailureType.RUNTIME: [
        re.compile(r"RuntimeError: (.+)", re.I),
        re.compile(r"ValueError: (.+)", re.I),
        re.compile(r"AttributeError: (.+)", re.I),
        re.compile(r"KeyError: (.+)", re.I),
        re.compile(r"IndexError: (.+)", re.I),
        re.compile(r"NameError: (.+)", re.I),
        re.compile(r"ZeroDivisionError", re.I),
    ],
    FailureType.INDENTATION: [
        re.compile(r"IndentationError: (.+)", re.I),
        re.compile(r"unexpected indent", re.I),
    ],
    FailureType.DEPENDENCY: [
        re.compile(r"No module named ['\"](.+?)['\"]", re.I),
        re.compile(r"ModuleNotFoundError", re.I),
        re.compile(r"pkg_resources.DistributionNotFound", re.I),
    ],
}

# ── JavaScript / TypeScript error patterns ────────────────────────────────────
NODE_PATTERNS = {
    FailureType.SYNTAX: [
        re.compile(r"SyntaxError: (.+)", re.I),
        re.compile(r"Unexpected token (.+)", re.I),
        re.compile(r"Cannot use import statement", re.I),
    ],
    FailureType.TYPE_ERROR: [
        re.compile(r"TypeError: (.+)", re.I),
        re.compile(r"is not a function", re.I),
        re.compile(r"Cannot read propert(?:y|ies) of (null|undefined)", re.I),
        re.compile(r"Cannot set propert(?:y|ies) of (null|undefined)", re.I),
        re.compile(r"TS\d{4}:.+", re.I),   # TypeScript compiler errors
    ],
    FailureType.RUNTIME: [
        re.compile(r"ReferenceError: (.+) is not defined", re.I),
        re.compile(r"RangeError: (.+)", re.I),
        re.compile(r"UnhandledPromiseRejection", re.I),
    ],
    FailureType.IMPORT: [
        re.compile(r"Cannot find module ['\"](.+?)['\"]", re.I),
        re.compile(r"Module not found: (.+)", re.I),
        re.compile(r"ERR_MODULE_NOT_FOUND", re.I),
    ],
    FailureType.TEST_FAILURE: [
        re.compile(r"Expected (.+) to (equal|be|match|contain) (.+)", re.I),
        re.compile(r"expect\((.+?)\)\.(.+?) failed", re.I),
        re.compile(r"AssertionError: (.+)", re.I),
    ],
}

# ── Java error patterns ───────────────────────────────────────────────────────
JAVA_PATTERNS = {
    FailureType.SYNTAX: [
        re.compile(r"error: (.+)", re.I),          # javac
        re.compile(r"\[ERROR\].+\.java:\[\d+,\d+\]", re.I),   # Maven
    ],
    FailureType.TYPE_ERROR: [
        re.compile(r"ClassCastException: (.+)", re.I),
        re.compile(r"NullPointerException", re.I),
        re.compile(r"incompatible types: (.+)", re.I),
    ],
    FailureType.RUNTIME: [
        re.compile(r"Exception in thread.+: (.+)", re.I),
        re.compile(r"StackOverflowError", re.I),
        re.compile(r"OutOfMemoryError", re.I),
        re.compile(r"ArrayIndexOutOfBoundsException", re.I),
    ],
    FailureType.IMPORT: [
        re.compile(r"cannot find symbol", re.I),
        re.compile(r"ClassNotFoundException: (.+)", re.I),
        re.compile(r"NoClassDefFoundError: (.+)", re.I),
    ],
    FailureType.TEST_FAILURE: [
        re.compile(r"AssertionError: (.+)", re.I),
        re.compile(r"FAILED: (.+)", re.I),
        re.compile(r"junit\.framework\.AssertionFailedError", re.I),
    ],
}

FILE_LINE_PATTERNS = [
    # Standard Python: File "test.py", line 10, in <module>
    re.compile(r'File ["\'](.+?)["\'].*?line (\d+)', re.DOTALL),
    # Pytest: tests/test_foo.py:10: in test_foo
    re.compile(r'^(.+?):(\d+): ', re.MULTILINE),
    # Java: at com.example.Foo(Foo.java:42)
    re.compile(r'at .+\((.+\.java):(\d+)\)', re.MULTILINE),
    # Node: at Object.<anonymous> (foo.js:10:5)
    re.compile(r'at .+\((.+\.(?:js|ts|jsx|tsx)):(\d+):', re.MULTILINE),
]

LINTING_SCORE_PATTERN = re.compile(
    r"^(.+?):(\d+):(\d+): ([A-Z]\d+) (.+)$", re.MULTILINE
)


class FailureClassifierAgent:
    """
    Takes raw test output + AST scan and produces classified Failure objects.
    Classification pipeline:
    1. Run pylint/AST scan on all source files
    2. Parse pytest stack traces
    3. Classify each failure into FailureType + Severity
    4. Deduplicate overlapping failures
    """

    def __init__(self, state: AgentState):
        self.state = state
        self.repo_path = Path(state.repo_path)
        self.ast_parser = ASTParser(str(self.repo_path))

    async def run_async(self) -> AgentState:
        """Async version to allow concurrent LLM scanning if we wanted, 
        but let's keep it simple for now."""
        return self.run()

    def run(self) -> AgentState:
        t0 = time.time()
        logger.info("[FailureClassifierAgent] Classifying failures...")

        failures: List[Failure] = []
        language = getattr(self.state, "repo_language", LanguageMode.PYTHON)

        if language == LanguageMode.PYTHON:
            # 1a. AST scan (deep, Python-only)
            failures.extend(self._classify_ast_failures())

            # 1b. Parse pytest output
            if self.state.pytest_json_report:
                stack_traces = [
                    str(t.get("call", {}).get("longrepr", ""))
                    for t in self.state.pytest_json_report.get("tests", [])
                    if t.get("outcome") in ("failed", "error")
                ]
                failures.extend(self._classify_pytest_failures(
                    stack_traces, self.state.pytest_output, self.state.pytest_json_report
                ))
        else:
            # 1c. Text-based classification for Node/Java
            pattern_map = NODE_PATTERNS if language == LanguageMode.NODE_JS else JAVA_PATTERNS
            failures.extend(self._classify_text_failures(
                self.state.pytest_output, pattern_map, language
            ))

        # 3. Proactive LLM scan (any language)
        source_files = getattr(self.state, "source_files", self.state.python_files)
        if len(failures) < 3 and source_files:
            logger.info("[FailureClassifierAgent] Running proactive LLM bug scan...")
            failures.extend(self._proactive_llm_scan(source_files, language))

        # 4. Deduplicate
        failures = self._deduplicate(failures)

        # Sort by severity
        severity_order = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}
        failures.sort(key=lambda f: severity_order.get(f.severity, 4))

        self.state.failures = failures
        elapsed = time.time() - t0

        self.state.timeline.append(CITimelineEvent(
            iteration=self.state.iteration,
            event_type="CLASSIFICATION",
            description=f"Classified {len(failures)} failures",
            failures_before=len(failures),
            duration_seconds=elapsed,
        ))

        logger.success(f"[FailureClassifierAgent] {len(failures)} failures classified in {elapsed:.2f}s")
        return self.state

    # ─────────────────────────────────────────
    def _classify_text_failures(
        self,
        raw_output: str,
        pattern_map: dict,
        language: str,
    ) -> List[Failure]:
        """
        Text-based failure classification for Node.js and Java.
        Applies language-specific regex patterns to raw test output.
        """
        failures: List[Failure]
        failures = []
        if not raw_output:
            return failures

        lines = raw_output.splitlines()

        for failure_type, patterns in pattern_map.items():
            for pattern in patterns:
                for m in pattern.finditer(raw_output):
                    message = m.group(0)[:300]  # cap length

                    # Try to extract file + line from surrounding context
                    start = max(0, m.start() - 300)
                    context = raw_output[start: m.end() + 200]

                    file_path = "unknown"
                    line_no: Optional[int] = None
                    for fp_pat in FILE_LINE_PATTERNS:
                        fp_m = fp_pat.search(context)
                        if fp_m:
                            candidate = fp_m.group(1)
                            if Path(candidate).exists() or (self.repo_path / candidate).exists():
                                file_path = str(self.repo_path / candidate)
                                try:
                                    line_no = int(fp_m.group(2))
                                except (IndexError, ValueError):
                                    pass
                                break

                    # If we found no file, use the first source file as a placeholder
                    if file_path == "unknown":
                        source_files = getattr(self.state, "source_files", [])
                        if source_files:
                            file_path = source_files[0]

                    severity = (
                        Severity.CRITICAL if failure_type in (FailureType.SYNTAX, FailureType.IMPORT)
                        else Severity.HIGH if failure_type in (FailureType.TYPE_ERROR, FailureType.RUNTIME)
                        else Severity.MEDIUM
                    )

                    failures.append(Failure(
                        failure_type=failure_type,
                        severity=severity,
                        file_path=file_path,
                        line_number=line_no,
                        message=message,
                        raw_trace=context[:500],
                    ))
        return failures

    def _proactive_llm_scan(
        self,
        source_files: Optional[List[str]] = None,
        language: str = LanguageMode.PYTHON,
    ) -> List[Failure]:
        """
        Scan source files with LLM to find obvious logic bugs without a test failure.
        Works for any language — LLM reads raw file content.
        """
        from backend.utils.llm_client import get_llm_client
        try:
            llm = get_llm_client()
        except Exception:
            return []

        proactive_failures: List[Failure] = []
        # Only scan non-test source files, limit to 1 for speed
        if source_files is None:
            source_files = [f for f in self.state.python_files if f not in self.state.test_files]
        scan_files = [f for f in source_files if f not in self.state.test_files][:1]

        for fp in scan_files:
            try:
                content = Path(fp).read_text(encoding="utf-8")
                # Make sure rel_path works even if fp is already absolute
                rel_path = os.path.relpath(fp, self.repo_path)
                
                lang_label = language.capitalize() if isinstance(language, str) else str(language)
                
                prompt = f"""Analyze this {lang_label} file for OBVIOUS runtime or logic bugs.
File: {rel_path}
Content:
{content}

Respond in JSON format:
{{
  "bugs": [
    {{
      "line": 10,
      "message": "Description of the bug",
      "severity": "HIGH",
      "type": "LOGIC"
    }}
  ]
}}
If no bugs found, return {{"bugs": []}}. 
ONLY return valid JSON. Do not include markdown or explanations.
"""
                resp = llm.generate(prompt)
                # Extract JSON
                json_str = resp.strip()
                if "```json" in json_str:
                    json_str = json_str.split("```json")[1].split("```")[0].strip()
                elif "```" in json_str:
                    json_str = json_str.split("```")[1].split("```")[0].strip()
                
                data = json.loads(json_str)
                for bug in data.get("bugs", []):
                    proactive_failures.append(Failure(
                        failure_type=bug.get("type", "LOGIC"),
                        severity=bug.get("severity", "MEDIUM"),
                        file_path=fp,
                        line_number=bug.get("line"),
                        message=bug.get("message", "Logic bug found by proactive scan"),
                        raw_trace=f"Proactive LLM Scan: {bug.get('message')}"
                    ))
            except Exception as e:
                logger.debug(f"[FailureClassifierAgent] Proactive scan failed for {fp}: {e}")
                
        return proactive_failures

    # ─────────────────────────────────────────
    def _classify_ast_failures(self) -> List[Failure]:
        failures: List[Failure] = []
        for fp in self.state.python_files:
            _, err = self.ast_parser.parse_file(fp)
            if err:
                ftype = FailureType.SYNTAX
                if "IndentationError" in err.node_type or "indent" in err.message.lower():
                    ftype = FailureType.INDENTATION
                failures.append(Failure(
                    failure_type=ftype,
                    severity=Severity.CRITICAL,
                    file_path=fp,
                    line_number=err.line,
                    column=err.col,
                    message=err.message,
                    raw_trace=f"AST parse failed: {err.node_type}",
                ))

            # Proactive check for undefined variables (catch errors even without failing tests)
            undefined_issues = self.ast_parser.find_undefined_names(fp)
            for issue in undefined_issues:
                failures.append(Failure(
                    failure_type=FailureType.LOGIC,
                    severity=Severity.HIGH,
                    file_path=fp,
                    line_number=issue.line,
                    column=issue.col,
                    message=issue.message,
                    raw_trace=f"Static analysis: {issue.message}",
                ))

            # Check imports
            ig = self.ast_parser.extract_imports(fp)
            for mod, name in ig.from_imports:
                if mod == "" and name not in ("__future__",):
                    failures.append(Failure(
                        failure_type=FailureType.IMPORT,
                        severity=Severity.HIGH,
                        file_path=fp,
                        line_number=0,
                        message=f"Suspicious from import: from {mod} import {name}",
                    ))

        return failures

    def _classify_pytest_failures(
        self,
        stack_traces: List[str],
        raw_output: str,
        json_report: Dict[str, Any]
    ) -> List[Failure]:
        failures: List[Failure] = []

        for trace in stack_traces:
            ftype, severity, message = self._detect_type(trace)
            file_path, line_number = self._extract_file_line(trace)

            failures.append(Failure(
                failure_type=ftype,
                severity=severity,
                file_path=file_path or "unknown",
                line_number=line_number,
                message=message,
                raw_trace=trace[:2000],  # cap trace length
            ))

        # Also scan full raw output for linting issues
        if raw_output:
            failures.extend(self._parse_lint_output(raw_output))

        # Generic TEST_FAILURE for each failed test in JSON report
        for test in json_report.get("tests", []):
            if test.get("outcome") in ("failed", "error"):
                nodeid = test.get("nodeid", "unknown")
                # Handle longrepr which might be dict or string
                longrepr = (test.get("call") or {}).get("longrepr", "")
                longrepr_str = str(longrepr) if longrepr else ""
                
                failures.append(Failure(
                    failure_type=FailureType.TEST_FAILURE,
                    severity=Severity.HIGH,
                    file_path=self._resolve_path(nodeid.split("::")[0]),
                    line_number=None,
                    message=f"Test failed: {nodeid}",
                    test_name=nodeid,
                    raw_trace=longrepr_str[:1000],
                ))

        return failures

    def _resolve_path(self, path_str: str) -> str:
        """Resolve path against repo root if relative."""
        if not path_str or path_str == "unknown":
            return path_str
        p = Path(path_str)
        if not p.is_absolute():
            # Join with repo_path and resolve
            return str((self.repo_path / p).resolve())
        return str(p)


    def _detect_type(self, trace: str) -> Tuple[FailureType, Severity, str]:
        for ftype, patterns in PATTERNS.items():
            for pat in patterns:
                m = pat.search(trace)
                if m:
                    msg = m.group(1) if m.lastindex else m.group(0)
                    severity = self._map_severity(ftype)
                    return ftype, severity, msg[:300]

        return FailureType.UNKNOWN, Severity.MEDIUM, trace.splitlines()[0][:300]

    def _map_severity(self, ftype: FailureType) -> Severity:
        mapping = {
            FailureType.SYNTAX: Severity.CRITICAL,
            FailureType.INDENTATION: Severity.CRITICAL,
            FailureType.IMPORT: Severity.HIGH,
            FailureType.DEPENDENCY: Severity.HIGH,
            FailureType.TYPE_ERROR: Severity.HIGH,
            FailureType.RUNTIME: Severity.MEDIUM,
            FailureType.TEST_FAILURE: Severity.MEDIUM,
            FailureType.LOGIC: Severity.MEDIUM,
            FailureType.LINTING: Severity.LOW,
        }
        return mapping.get(ftype, Severity.MEDIUM)

    def _extract_file_line(self, trace: str) -> Tuple[Optional[str], Optional[int]]:
        for pat in FILE_LINE_PATTERNS:
            matches = pat.findall(trace)
            if matches:
                # Use the LAST match (most recent call frame usually closest to error)
                file_path, line = matches[-1]
                return self._resolve_path(file_path), int(line)
        return None, None

    def _parse_lint_output(self, output: str) -> List[Failure]:
        failures = []
        for m in LINTING_SCORE_PATTERN.finditer(output):
            fp, line, col, code, msg = m.groups()
            failures.append(Failure(
                failure_type=FailureType.LINTING,
                severity=Severity.LOW,
                file_path=fp,
                line_number=int(line),
                column=int(col),
                message=f"{code}: {msg}",
            ))
        return failures

    def _deduplicate(self, failures: List[Failure]) -> List[Failure]:
        seen = set()
        unique = []
        for f in failures:
            key = (f.failure_type, f.file_path, f.line_number, f.message[:80])
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique
