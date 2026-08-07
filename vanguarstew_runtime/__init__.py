"""Private, self-hosted runtime for Vanguarstew maintainer assistance.

The runtime is deliberately separate from the benchmark package.  It persists
operational state locally, receives or polls for pull-request work, and never
publishes reviewer output.  It does not add a second agent entrypoint: review
execution still uses :mod:`agent.review` and the project's managed-inference
contract.
"""

from .config import RuntimeConfig, load_runtime_config
from .service import RuntimeService
from .state import RuntimeState

__all__ = ["RuntimeConfig", "RuntimeService", "RuntimeState", "load_runtime_config"]

