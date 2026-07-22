"""ShipMBLang onboarding command wrapper."""

from driplm.onboarding import *  # noqa: F401,F403
from driplm.onboarding import build_onboarding_manifest, main, run_onboarding_checks

__all__ = ["build_onboarding_manifest", "main", "run_onboarding_checks"]
