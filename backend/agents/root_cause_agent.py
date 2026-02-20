"""
backend/agents/root_cause_agent.py
=====================================
RootCauseAgent — Uses LLM (Gemini FREE / GPT-4o) + dependency graph
traversal to perform backward reasoning and find the MINIMAL root fault.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.utils.ast_parser import ASTParser
from backend.utils.llm_client import get_llm_client
from backend.utils.logger import logger
from backend.utils.models import AgentState, CITimelineEvent, Failure
from config.settings import settings


ROOT_CAUSE_SYSTEM_PROMPT = """You are an expert Polyglot Software Debugger.
Your job is to find the TRUE root cause of a software failure — not the symptom.

Rules:
- Trace backward from the failure through the call stack and context
- Identify the MINIMAL fault: the single change that would fix the root problem
- Never suggest refactoring unrelated code
- Output ONLY valid JSON

Output Schema:
{
  "root_cause_file": "<absolute or relative file path>",
  "root_cause_line": <integer line number or null>,
  "root_cause_type": "<one of: SYNTAX|IMPORT|TYPE_ERROR|LOGIC|DEPENDENCY|RUNTIME|INDENTATION>",
  "explanation": "<clear explanation of why this is the root cause>",
  "fault_chain": ["<file1>:<line1> reason", "<file2>:<line2> reason"],
  "confidence": <0.0-1.0>
}
"""


class RootCauseAgent:
    """
    LLM-powered root cause analysis using Gemini (free) or OpenAI.
    Gracefully degrades to static analysis if LLM is unavailable.
    """

    def __init__(self, state: AgentState):
        self.state = state
        self.repo_path = Path(state.repo_path)
        self.ast_parser = ASTParser(str(self.repo_path))

    def run(self) -> AgentState:
        t0 = time.time()
        logger.info(f"[RootCauseAgent] Analyzing {len(self.state.failures)} failures...")

        # Try to get LLM client
        try:
            self.llm = get_llm_client()
            use_llm = True
        except Exception as e:
            logger.warning(f"[RootCauseAgent] LLM unavailable ({e}) — using static analysis only")
            use_llm = False

        # Skip LLM if fallback already triggered (rate-limited in a previous agent)
        if getattr(self.state, "fallback_triggered", False):
            use_llm = False
            logger.info("[RootCauseAgent] Fallback mode active — using static analysis only (skipping LLM)")

        priority_failures = [
            f for f in self.state.failures
            if f.severity in ("CRITICAL", "HIGH", "MEDIUM")
        ]

        # Deduplicate and parallelize
        from concurrent.futures import ThreadPoolExecutor
        
        # 1. Group failures by file for unique analysis
        file_to_failure = {}
        for f in priority_failures:
            if f.file_path not in file_to_failure:
                file_to_failure[f.file_path] = f

        if use_llm and file_to_failure:
            max_workers = min(len(file_to_failure), 4)
            logger.info(f"[RootCauseAgent] Launching parallel LLM analysis with {max_workers} workers...")
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(self._analyze_with_llm, f): f for f in file_to_failure.values()}
                for future in futures:
                    try:
                        ok = future.result()
                        if not ok:
                            use_llm = False # Global signal to stop LLM if rate-limited
                    except Exception as e:
                        logger.error(f"[RootCauseAgent] Worker failed: {e}")

        # Always ensure static coverage for all failures
        for failure in self.state.failures:
            self._analyze_static(failure)

        elapsed = time.time() - t0
        self.state.timeline.append(CITimelineEvent(
            iteration=self.state.iteration,
            event_type="ROOT_CAUSE",
            description=f"Root cause analyzed for {len(priority_failures)} failures ({'static' if not use_llm else 'LLM'})",
            duration_seconds=elapsed,
        ))

        logger.success(f"[RootCauseAgent] Done in {elapsed:.2f}s")
        return self.state


    # ─────────────────────────────────────────
    def _analyze_with_llm(self, failure: Failure) -> bool:
        """Returns True if LLM succeeded, False if it failed (so caller can switch to static)."""
        context = self._build_context(failure)
        if not context:
            self._analyze_static(failure)
            return True  # Not an LLM failure, just no context

        prompt = f"""
Analyze this failure and provide the root cause.

=== FAILURE ===
Type: {failure.failure_type}
Severity: {failure.severity}
File: {failure.file_path}
Line: {failure.line_number}
Message: {failure.message}

=== STACK TRACE ===
{failure.raw_trace or 'N/A'}

=== SOURCE CONTEXT ===
{context['source_window']}

=== DEPENDENCY CHAIN ===
{self._format_deps(context['dep_chain'])}

Respond with valid JSON only.
"""
        try:
            result = self.llm.complete(
                system_prompt=ROOT_CAUSE_SYSTEM_PROMPT,
                user_prompt=prompt,
                temperature=self.state.current_temperature,
                seed=settings.RANDOM_SEED,
            )
            rc = json.loads(result)
            failure.root_cause_file = rc.get("root_cause_file", failure.file_path)
            failure.root_cause_line = rc.get("root_cause_line", failure.line_number)
            failure.message = f"{failure.message} | ROOT: {rc.get('explanation', '')[:150]}"
            logger.debug(f"[RootCauseAgent] ✅ LLM root cause for {failure.failure_id[:8]}: {failure.root_cause_file}:{failure.root_cause_line}")
            return True
        except Exception as e:
            err_str = str(e)
            logger.warning(f"[RootCauseAgent] LLM failed for {failure.failure_id[:8]}: {e} — falling back to static")
            # Signal rate-limit to caller so it stops trying LLM
            if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                self._analyze_static(failure)
                return False  # Signal: stop using LLM
            self._analyze_static(failure)
            return True  # Transient error, caller can still try LLM for next failure


    def _analyze_static(self, failure: Failure) -> None:
        """Fallback: use AST info as root cause (no LLM needed)."""
        resolved_file = failure.file_path

        # Heuristic: map test file -> source file
        if resolved_file and resolved_file != "unknown":
            p = Path(resolved_file)
            # Basic Convention: test_foo.py -> foo.py or foo.test.js -> foo.js
            stem = p.name.split('.')[0] # simple stem
            if "test" in stem:
                 # Try to strip 'test_' or '_test' or '.test'
                 clean = stem.replace("test_", "").replace("_test", "").replace(".test", "")
                 # Candidates for source file
                 candidates = [
                     p.parent / f"{clean}.py",
                     p.parent / f"{clean}.js",
                     p.parent / f"{clean}.ts",
                     p.parent / f"{clean}.java",
                     self.repo_path / "src" / f"{clean}.py",
                     self.repo_path / "src" / f"{clean}.js",
                     self.repo_path / "src" / f"{clean}.ts",
                     self.repo_path / "src" / f"{clean}.java",
                 ]
                 for c in candidates:
                     if c.exists() and c != p:
                         resolved_file = str(c)
                         logger.info(f"[RootCauseAgent] Mapped test {p.name} -> source {c.name}")
                         break

        failure.root_cause_file = resolved_file
        failure.root_cause_line = failure.line_number
        logger.debug(f"[RootCauseAgent] Static root cause: {failure.root_cause_file}:{failure.root_cause_line}")

    def _build_context(self, failure: Failure) -> Optional[Dict[str, Any]]:
        file_path = failure.root_cause_file or failure.file_path
        if not file_path or file_path == "unknown":
            return None
        # get_source_window IS polyglot (text read)
        source_window = self.ast_parser.get_source_window(file_path, failure.line_number or 1, window=15)
        dep_chain = self._get_dep_chain(file_path, depth=2)
        return {"source_window": source_window, "dep_chain": dep_chain}

    def _get_dep_chain(self, file_path: str, depth: int) -> List[str]:
        chain: List[str] = []
        visited = set()
        def _traverse(fp: str, d: int) -> None:
            if d <= 0 or fp in visited:
                return
            visited.add(fp)
            for dep in self.state.dependency_graph.get(fp, [])[:3]:
                chain.append(dep)
                _traverse(dep, d - 1)
        _traverse(file_path, depth)
        return chain

    def _format_deps(self, deps: List[str]) -> str:
        return "\n".join(f"  → {d}" for d in deps[:10]) if deps else "No dependencies"
