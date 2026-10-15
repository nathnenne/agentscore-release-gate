"""AgentScore release-gate CLI (TSK_123).

Public API surface kept tiny on purpose — most users invoke `agentscore`
as a console script. Importing the package programmatically is only
useful for embedding the gate logic in a custom CI runner.
"""

from .decision import (
    DEFAULT_FAIL_ON,
    DecisionReport,
    compute_release_decision,
    decision_should_fail,
)
from .intelligence import (
    DecisionIntelligence,
    build_decision_intelligence,
)

__all__ = [
    "DEFAULT_FAIL_ON",
    "DecisionIntelligence",
    "DecisionReport",
    "build_decision_intelligence",
    "compute_release_decision",
    "decision_should_fail",
]

__version__ = "0.1.0"
