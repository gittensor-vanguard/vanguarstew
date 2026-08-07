"""OpenVang's policy-only multi-agent factory foundation.

This package deliberately defines *who may propose and prepare work*, not how
to control a wallet, submit a chain transaction, merge code, or publish a
review.  Those owner-level effects remain outside the factory until a separate
approved adapter and signer boundary exists.
"""

from .factory import (
    ActionIntent,
    ActionKind,
    ArtifactClass,
    FactoryPolicy,
    MemoryScope,
    Role,
    RoleContract,
)
from .isolated import IsolatedExecutionAdapter, IsolatedExecutionError, IsolatedExecutionReceipt
from .memory import (
    AuthenticatedCipher,
    FactoryMemoryError,
    FactoryMemoryVault,
    FernetMemoryCipher,
    PrivateMemoryRecord,
    SharedMemoryCommitment,
)
from .scheduler import FactoryScheduler, FactoryTask, SchedulerError
from .subnet import (
    ReadOnlySubnetStateAdapter,
    ReadOnlySubnetStateSource,
    SubnetStateError,
    SubnetStatePlan,
    SubnetStateReceipt,
)

__all__ = [
    "ActionIntent",
    "ActionKind",
    "ArtifactClass",
    "FactoryPolicy",
    "MemoryScope",
    "Role",
    "RoleContract",
    "FactoryScheduler",
    "FactoryTask",
    "SchedulerError",
    "IsolatedExecutionAdapter",
    "IsolatedExecutionError",
    "IsolatedExecutionReceipt",
    "AuthenticatedCipher",
    "FactoryMemoryError",
    "FactoryMemoryVault",
    "FernetMemoryCipher",
    "PrivateMemoryRecord",
    "SharedMemoryCommitment",
    "ReadOnlySubnetStateAdapter",
    "ReadOnlySubnetStateSource",
    "SubnetStateError",
    "SubnetStatePlan",
    "SubnetStateReceipt",
]
