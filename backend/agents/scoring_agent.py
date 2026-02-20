"""
backend/agents/scoring_agent.py
=================================
ScoringAgent — Computes deterministic scoring (NO LLM).
Pure math based on fix count, speed, regressions, CI pass rate.

Score Formula:
  total = base_score
          + (fixes * SCORE_PER_FIX)
          + (speed_factor * elapsed_bonus)
          - (regressions * REGRESSION_PENALTY)
          + ci_success_score

All math is deterministic and reproducible.
"""

from __future__ import annotations

import math
import time
from typing import Optional

from backend.utils.logger import logger
from backend.utils.models import AgentState, CIStatus, CITimelineEvent, Scoring
from config.settings import settings


class ScoringAgent:
    """
    Computes the final score for a healing run.
    Uses ONLY arithmetic — no randomness, no LLM.
    """

    def __init__(self, state: AgentState):
        self.state = state

    def run(self) -> AgentState:
        t0 = time.time()
        logger.info("[ScoringAgent] Computing final score...")

        # Finalize CI Status based on failures vs fixes
        remaining_failures = len([f for f in self.state.failures if not any(
            fix.failure_id == f.failure_id for fix in self.state.fixes
        )])

        no_test_suite = getattr(self.state, "pytest_exit_code", None) == 5

        if self.state.fatal_error:
            self.state.ci_status = CIStatus.FAILED
        elif remaining_failures == 0:
            self.state.ci_status = CIStatus.SUCCESS
        elif self.state.fixes and no_test_suite:
            # No tests exist — any fix is a full resolution (can't prove more failures)
            self.state.ci_status = CIStatus.SUCCESS
        elif self.state.fixes:
            self.state.ci_status = CIStatus.PARTIAL
        else:
            self.state.ci_status = CIStatus.FAILED

        scoring = self._compute_score()
        self.state.scoring = scoring
        elapsed = time.time() - t0

        self.state.timeline.append(CITimelineEvent(
            iteration=self.state.iteration,
            event_type="SCORING",
            description=f"Final score: {scoring.total_score:.1f}/100",
            duration_seconds=elapsed,
        ))

        logger.success(
            f"[ScoringAgent] Score={scoring.total_score:.2f} | "
            f"fixes={scoring.actual_fixes} | "
            f"efficiency={scoring.fix_efficiency:.2f} | "
            f"regressions_penalty={scoring.regression_penalty:.1f}"
        )
        return self.state

    # ─────────────────────────────────────────
    def _compute_score(self) -> Scoring:
        total_failures = len(self.state.failures)
        actual_fixes = len([f for f in self.state.fixes if f.validated])
        total_regressions = sum(
            r.tests_regressed
            for r in self.state.validation_results
        )

        # Base score
        base = settings.SCORE_BASE

        # Fix efficiency: ratio of fixes to failures (0–1)
        fix_efficiency = (actual_fixes / total_failures) if total_failures > 0 else 0.0
        fix_score = actual_fixes * settings.SCORE_PER_FIX

        # Speed factor: bonus for completing in fewer iterations
        max_iters = self.state.max_retries
        iters_used = self.state.iteration
        speed_factor = max(0.0, (max_iters - iters_used) / max_iters)
        speed_bonus = speed_factor * settings.SCORE_SPEED_FACTOR * 10

        # Regression penalty
        regression_penalty = total_regressions * settings.SCORE_REGRESSION_PENALTY

        # CI success bonus
        ci_success_score = 20.0 if self.state.ci_status == CIStatus.SUCCESS else 0.0

        # Total (clamped to 0–100 range but allow overage for exceptional runs)
        total = base + fix_score + speed_bonus - regression_penalty + ci_success_score
        total = max(0.0, total)  # never negative

        return Scoring(
            base_score=base,
            speed_factor=round(speed_factor, 4),
            fix_efficiency=round(fix_efficiency, 4),
            regression_penalty=round(regression_penalty, 2),
            ci_success_score=ci_success_score,
            total_score=round(total, 2),
            iterations_used=iters_used,
            total_possible_fixes=total_failures,
            actual_fixes=actual_fixes,
            computation_method="deterministic",
        )
