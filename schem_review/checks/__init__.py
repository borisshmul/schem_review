"""Checks package — imports all check modules so their @register decorators fire."""
from schem_review.checks import drc, ee, ethernet, power  # noqa: F401 — side-effects register checks
from schem_review.checks.registry import get_all_checks, run_checks

__all__ = ["get_all_checks", "run_checks"]
