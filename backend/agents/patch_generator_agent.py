"""
backend/agents/patch_generator_agent.py
=========================================
PatchGeneratorAgent — Uses GPT-4o to generate MINIMAL, DETERMINISTIC,
REVERSIBLE patches for each classified failure.

Fallback: If OpenAI quota is exhausted or unavailable, automatically
switches to a deterministic AST-based rule engine for common fix types.

Rules enforced:
- minimal diff (no unrelated changes)
- no test rewriting unless test is broken
- no hallucinated files
- style-compliant
- deterministic (seeded generation)
- reversible (captures original code)
"""

from __future__ import annotations

import difflib
import json
import time
from pathlib import Path
from typing import List, Optional


from backend.utils.ast_parser import ASTParser
from backend.utils.llm_client import get_llm_client
from backend.utils.logger import logger
from backend.utils.models import (
    AgentState,
    CITimelineEvent,
    Failure,
    FailureType,
    Patch,
    PatchType,
    LanguageMode,
)
from config.settings import settings


PATCH_SYSTEM_PROMPT = """You are an expert Python bug fixer.
Your output must be ONLY the complete fixed Python file, wrapped in a ```python code block.

ABSOLUTE RULES:
1. PRESERVE every function — do NOT remove or rename any function
2. PRESERVE all type hints (e.g., -> float, a: float)
3. PRESERVE all function parameter names exactly
4. PRESERVE the module docstring text
5. Fix ONLY actual bugs; do not refactor or simplify
6. Add missing imports at the TOP
7. Output the full file — no truncation

Common bugs:
- Missing `:` at end of def/class/if/for/while line
- `return str(x/y)` when function returns float
- Wrong variable name (e.g., `num` when parameter is `n`)
- Missing `import math` when math.* is used
- Inverted logic operator (`not in` vs `in`)
- Wrong indentation level

Respond with ONLY this format:
```python
<complete fixed file>
```
"""



class PatchGeneratorAgent:
    """
    Generates targeted code patches for each failure.
    Uses GPT-4o with seeded determinism.
    Validates patches with AST before accepting.
    """

    def __init__(self, state: AgentState):
        self.state = state
        self.repo_path = Path(state.repo_path)
        self.ast_parser = ASTParser(str(self.repo_path))
        try:
            self.llm = get_llm_client()
        except Exception as e:
            logger.warning(f"[PatchGeneratorAgent] LLM init failed: {e} — fallback mode")
            self.llm = None
            self._use_fallback = True

        # If both LLMs are known-exhausted, skip directly to fallback
        if self.llm is not None:
            try:
                # Cheap check: only skip init if provider is known rate-limited
                pass
            except Exception:
                self._use_fallback = True

    # Flag set when OpenAI quota is exhausted — switch to fallback
    _use_fallback: bool = False

    def run(self) -> AgentState:
        t0 = time.time()
        logger.info(f"[PatchGeneratorAgent] Generating patches for {len(self.state.failures)} failures...")

        # 1. Group failures by file to avoid overlapping patches in same file
        file_to_failures = {}
        for failure in self.state.failures:
            target_file = failure.root_cause_file or failure.file_path
            if target_file == "unknown":
                continue
            if target_file not in file_to_failures:
                file_to_failures[target_file] = failure # Use the first failure found for this file

        patches: List[Patch] = []
        
        # 2. Parallel Processing
        from concurrent.futures import ThreadPoolExecutor
        max_workers = min(len(file_to_failures), 4) # cap at 4 parallel LLM calls to prevent rate limits
        
        def process_file(target_file, failure):
            if self._use_fallback:
                return self._fallback_patch(failure, target_file)
            else:
                return self._generate_patch(failure, target_file)

        if file_to_failures:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(process_file, f, fail) for f, fail in file_to_failures.items()]
                for future in futures:
                    patch = future.result()
                    if patch:
                        patches.append(patch)

        self.state.patches = patches
        elapsed = time.time() - t0

        self.state.timeline.append(CITimelineEvent(
            iteration=self.state.iteration,
            event_type="PATCH_GENERATION",
            description=f"Generated {len(patches)} patches (Parallel Core)",
            duration_seconds=elapsed,
        ))

        logger.success(f"[PatchGeneratorAgent] {len(patches)} patches generated in {elapsed:.2f}s (workers={max_workers})")
        return self.state

    # ─────────────────────────────────────────
    def _generate_patch(self, failure: Failure, target_file: str) -> Optional[Patch]:
        try:
            original_code = Path(target_file).read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            logger.warning(f"[PatchGeneratorAgent] File not found: {target_file}")
            return None

        # Determine language for prompt
        ext = Path(target_file).suffix
        lang_label = \
            "Python" if ext == ".py" else \
            "JavaScript" if ext in (".js", ".jsx", ".mjs", ".cjs") else \
            "TypeScript" if ext in (".ts", ".tsx") else \
            "Java" if ext == ".java" else \
            "Source"

        # Cap source size for LLM context
        code_for_llm = original_code
        if len(original_code) > 12000:
            lines = original_code.splitlines()
            start = max(0, (failure.line_number or 1) - 30)
            end = min(len(lines), (failure.line_number or 1) + 30)
            code_for_llm = "\n".join(lines[start:end])

        prompt = f"""Fix ALL bugs in this {lang_label} file.
Preserve ALL functions, type hints, parameter names, and existing style.

=== REPORTED FAILURE ===
Type    : {failure.failure_type}
Message : {failure.message}
File    : {target_file}
Line    : {failure.line_number}

=== BUGS TO FIND AND FIX ===
1. Syntax errors (missing braces, semicolons, colons)
2. Undefined variables or imports
3. Type mismatches or null pointer exceptions
4. Logic errors causing the reported failure
5. Wrong indentation or nesting

=== SOURCE FILE ({len(code_for_llm.splitlines())} lines — return ALL of them fixed) ===
```{ext[1:] if ext.startswith('.') else 'code'}
{code_for_llm}
```

Output ONLY the complete fixed file inside a markdown code block.
Do NOT duplicate chunks of code. Return ONLY the single, valid, complete file content.
"""

        try:
            if self.llm is None:
                return self._fallback_patch(failure, target_file)

            result = self.llm.complete(
                system_prompt=PATCH_SYSTEM_PROMPT,
                user_prompt=prompt,
                temperature=self.state.current_temperature,
                seed=settings.RANDOM_SEED,
            )

            # Extract code from any markdown block (```python, ```javascript, etc.)
            import re as _re
            # robust regex to capture content inside fences, handling optional language tag
            code_matches = _re.findall(r'```(?:[\w\+\-#]+)?\s*(.*?)```', result, _re.DOTALL)
            
            if code_matches:
                # Use the LAST block, as chatty models often quote the buggy code first
                patched_code = code_matches[-1].strip()
            else:
                # If no blocks, assume raw output is the code (risky but handles 'just code' responses)
                patched_code = result.strip()

            reasoning = "LLM-generated fix (polyglot mode)"
            patch_type_str = "logic_correction"

            # Validate patch (syntax check only for Python currently)
            if not self._validate_syntax(patched_code, target_file):
                logger.warning(f"[PatchGeneratorAgent] Invalid syntax in patch for {target_file}, skipping")
                return None

            # Compute diff
            diff = self._compute_diff(original_code, patched_code, target_file)

            # Check diff size
            diff_lines = [l for l in diff.splitlines() if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]
            if len(diff_lines) > settings.PATCH_MAX_LINES:
                logger.warning(f"[PatchGeneratorAgent] Patch too large ({len(diff_lines)} lines), rejecting")
                return None

            # Map patch type
            try:
                patch_type = PatchType(patch_type_str)
            except ValueError:
                patch_type = PatchType.LOGIC_CORRECTION

            patch = Patch(
                failure_id=failure.failure_id,
                patch_type=patch_type,
                file_path=target_file,
                original_code=original_code,
                patched_code=patched_code,
                diff=diff,
                line_start=failure.line_number or 0,
                line_end=(failure.line_number or 0) + len(diff_lines),
                reasoning=reasoning[:500],
                deterministic=True,
            )

            logger.info(f"[PatchGeneratorAgent] Patch {patch.patch_id[:8]} for {Path(target_file).name} — {len(diff_lines)} lines changed")
            return patch

        except Exception as e:
            err_str = str(e)
            # Rate limit (429) or quota exhausted — immediately switch to rule-based fallback
            # (Retrying is pointless for daily token-limit exhaustion)
            if ("429" in err_str or "Too Many Requests" in err_str or
                    "rate" in err_str.lower() or "quota" in err_str.lower() or
                    "insufficient_quota" in err_str):
                logger.warning(
                    f"[PatchGeneratorAgent] LLM unavailable (rate/quota) — switching permanently to rule-based fallback"
                )
                self._use_fallback = True
                self.state.fallback_triggered = True
                return self._fallback_patch(failure, target_file)
            logger.error(f"[PatchGeneratorAgent] Failed to generate patch for {target_file}: {e}")
            self.state.fallback_triggered = True
            return self._fallback_patch(failure, target_file)

    # ─────────────────────────────────────────
    # FALLBACK: Deterministic Rule-Based Patch Engine
    # Handles the most common failure types without any LLM call
    # ─────────────────────────────────────────

    def _fallback_patch(self, failure: Failure, target_file: str) -> Optional[Patch]:
        """Apply deterministic rule-based fixes when LLM is unavailable."""
        try:
            original_code = Path(target_file).read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return None

        patched_code = original_code
        patch_type = PatchType.SYNTAX_CORRECTION
        reasoning = "Rule-based fallback fix"
        changes_made = []

        ftype = failure.failure_type

        if ftype in ("SYNTAX", "INDENTATION", FailureType.SYNTAX, FailureType.INDENTATION):
            patched_code, reasoning = self._fix_syntax_rules(original_code, failure)
            patch_type = PatchType.SYNTAX_CORRECTION

        elif ftype in ("IMPORT", FailureType.IMPORT):
            patched_code, reasoning = self._fix_import_rules(original_code, failure)
            patch_type = PatchType.IMPORT_REPAIR

        elif ftype in ("TYPE_ERROR", FailureType.TYPE_ERROR, "TEST_FAILURE", FailureType.TEST_FAILURE):
            patched_code, reasoning = self._fix_type_rules(original_code, failure)
            patch_type = PatchType.TYPE_FIX

        elif ftype in ("RUNTIME", FailureType.RUNTIME):
            patched_code, reasoning = self._fix_runtime_rules(original_code, failure)
            patch_type = PatchType.LOGIC_CORRECTION

        elif ftype in ("LOGIC", FailureType.LOGIC, "LINTING", FailureType.LINTING,
                       "UNKNOWN", FailureType.UNKNOWN):
            # For LOGIC/LINTING bugs, try all rules in sequence
            result, r = self._fix_syntax_rules(original_code, failure)
            if result != original_code:
                patched_code, reasoning = result, r
                changes_made.append(r)

            result2, r2 = self._fix_type_rules(patched_code, failure)
            if result2 != patched_code:
                patched_code, reasoning = result2, r2
                changes_made.append(r2)

            result3, r3 = self._fix_runtime_rules(patched_code, failure)
            if result3 != patched_code:
                patched_code, reasoning = result3, r3
                changes_made.append(r3)

            # Fix lru_cache on instance methods by removing decorator
            import re
            if '@lru_cache' in patched_code and 'self' in patched_code:
                lines = patched_code.splitlines()
                fixed_lines = []
                skip_next = False
                for i, line in enumerate(lines):
                    if skip_next:
                        skip_next = False
                        continue
                    if '@lru_cache' in line and i + 1 < len(lines) and 'self' in lines[i + 1]:
                        changes_made.append(f"Removed @lru_cache from instance method (line {i+1})")
                        skip_next = False  # keep the def line, just skip decorator
                        continue  # skip the decorator line
                    fixed_lines.append(line)
                patched_code = '\n'.join(fixed_lines)
                if not patched_code.endswith('\n'):
                    patched_code += '\n'

            reasoning = '; '.join(changes_made) if changes_made else 'Applied all available rules'
            patch_type = PatchType.LOGIC_CORRECTION

        if patched_code == original_code:
            logger.warning(f"[PatchGeneratorAgent] Fallback: no rule matched for {Path(target_file).name}")
            return None

        if not self._validate_syntax(patched_code, target_file):
            logger.warning(f"[PatchGeneratorAgent] Fallback patch failed syntax check for {target_file}")
            return None

        diff = self._compute_diff(original_code, patched_code, target_file)
        logger.info(f"[PatchGeneratorAgent] ⚙️  Fallback rule patch applied to {Path(target_file).name}")

        return Patch(
            failure_id=failure.failure_id,
            patch_type=patch_type,
            file_path=target_file,
            original_code=original_code,
            patched_code=patched_code,
            diff=diff,
            line_start=failure.line_number or 0,
            line_end=(failure.line_number or 0) + 5,
            reasoning=f"[RULE-BASED] {reasoning}",
            deterministic=True,
        )

    def _fix_syntax_rules(self, code: str, failure: Failure) -> tuple[str, str]:
        """Fix common syntax / indentation errors deterministically."""
        lines = code.splitlines()
        fixed_lines = list(lines)
        changes = []

        line_idx = (failure.line_number or 1) - 1

        for i, line in enumerate(lines):
            stripped = line.rstrip()

            # Fix 1: missing colon on def/class/if/for/while/with/elif/else/try/except/finally
            import re
            if re.match(r'^\s*(def |class |if |for |while |with |elif |else|try|except|finally).*[^:]$', stripped):
                if not stripped.endswith(':'):
                    fixed_lines[i] = stripped + ':'
                    changes.append(f"Line {i+1}: added missing colon")

            # Fix 2: IndentationError — re-align to nearest valid indent
            elif abs(i - line_idx) <= 3 and failure.failure_type in ("INDENTATION", FailureType.INDENTATION):
                if i > 0:
                    prev = fixed_lines[i - 1]
                    prev_indent = len(prev) - len(prev.lstrip())
                    cur_indent = len(line) - len(line.lstrip())
                    # If current indent > expected (extra indent)
                    if cur_indent > prev_indent + 4:
                        correct_indent = ' ' * (prev_indent + 4)
                        fixed_lines[i] = correct_indent + line.lstrip()
                        changes.append(f"Line {i+1}: corrected indentation")

        patched = '\n'.join(fixed_lines)
        if not patched.endswith('\n'):
            patched += '\n'
            
        reasoning = '; '.join(changes) if changes else 'Applied syntax rules'
        return patched, reasoning

    def _fix_import_rules(self, code: str, failure: Failure) -> tuple[str, str]:
        """Fix missing imports by prepending them."""
        import re
        missing = re.search(r"No module named '([^']+)'", failure.message)
        if not missing:
            missing = re.search(r"cannot import name '([^']+)'", failure.message)
        if not missing:
            return code, "No import pattern matched"

        mod = missing.group(1).split('.')[0]
        import_line = f"import {mod}\n"

        if import_line.strip() in code:
            return code, f"{mod} already imported"

        # Find first non-docstring, non-comment line to insert import
        lines = code.splitlines(keepends=True)
        insert_at = 0
        for i, ln in enumerate(lines):
            if ln.strip() and not ln.strip().startswith('#') and not ln.strip().startswith('"""') and not ln.strip().startswith("'''"):
                insert_at = i
                break
        lines.insert(insert_at, import_line)
        return ''.join(lines), f"Inserted 'import {mod}' at line {insert_at+1}"

    def _fix_type_rules(self, code: str, failure: Failure) -> tuple[str, str]:
        """Fix common type coercions (e.g. str() wrapping numeric return)."""
        import re
        # Fix: return str(x / y) → return x / y
        patched = re.sub(r'return str\((.+?)\)', r'return \1', code)
        # Fix: return str(x) → return x  (in functions returning int/float)
        if patched != code:
            return patched, "Removed str() wrapper from numeric return value"
        return code, "No type fix rule matched"

    def _fix_runtime_rules(self, code: str, failure: Failure) -> tuple[str, str]:
        """Fix NameError and other runtime issues."""
        import re
        msg = failure.message
        
        # 1. NameError: name 'math' is not defined -> Add import
        # Regex checks for "name 'X' is not defined" (message from classifier) OR "NameError: name 'X'..."
        match = re.search(r"name '(\w+)' is not defined", msg)
        if match:
            missing_var = match.group(1)
            # Heuristic: if variable is a standard library module
            std_libs = {"math", "json", "os", "sys", "re", "random", "datetime", "time"}
            if missing_var in std_libs:
                 # Reuse import fixer logic but forced
                 return self._fix_import_rules(code, Failure(
                     failure_type=FailureType.IMPORT, 
                     severity=failure.severity, 
                     file_path=failure.file_path, 
                     message=f"No module named '{missing_var}'"
                 ))

            # 2. Variable Typos (e.g. num -> n)
            # Find function def enclosing the error line
            lines = code.splitlines()
            err_line_idx = (failure.line_number or 1) - 1
            
            # Search backwards for def ...
            param_name = None
            for i in range(err_line_idx, -1, -1):
                if lines[i].strip().startswith("def "):
                    # Extract params: def foo(n: int) -> int:
                    # simplistic extraction: parens content
                    m_def = re.search(r"def \w+\s*\((.+?)\)", lines[i])
                    if m_def:
                        params_str = m_def.group(1)
                        # Split by comma, remove type hints
                        params = [p.split(":")[0].strip() for p in params_str.split(",")]
                        # Check if any param looks like the missing var (e.g. 'n' vs 'num')
                        if missing_var == "num" and "n" in params:
                            param_name = "n"
                        elif missing_var == "n" and "num" in params:
                            param_name = "num"
                    break
            
            if param_name:
                # Replace 'num' with 'n' on the error line
                lines[err_line_idx] = re.sub(rf"\b{missing_var}\b", param_name, lines[err_line_idx])
                return "\n".join(lines), f"Replaced undefined '{missing_var}' with parameter '{param_name}'"

        return code, "No runtime fix rule matched"

    def _validate_syntax(self, code: str, file_path: str) -> bool:
        """
        Validate syntax using Python's AST parser.
        For non-Python files, we currently skip validation (return True).
        """
        if not file_path.endswith(".py"):
            return True

        import ast
        try:
            ast.parse(code)
            return True
        except SyntaxError as e:
            logger.debug(f"[PatchGeneratorAgent] Syntax invalid in generated patch: {e}")
            return False
        except Exception:
            return False

    def _compute_diff(self, original: str, patched: str, file_path: str) -> str:
        orig_lines = original.splitlines(keepends=True)
        patched_lines = patched.splitlines(keepends=True)
        diff = difflib.unified_diff(
            orig_lines,
            patched_lines,
            fromfile=f"a/{Path(file_path).name}",
            tofile=f"b/{Path(file_path).name}",
            lineterm="",
        )
        return "".join(diff)
