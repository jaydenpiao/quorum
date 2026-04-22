"""Fly.io actuator — deploy + rollback orchestration over ``flyctl``."""

from apps.api.app.services.actuators.fly.actions import (
    FlyActionError,
    FlyRollbackImpossibleError,
    deploy,
    rollback_deploy,
)
from apps.api.app.services.actuators.fly.client import (
    FlyBinaryMissing,
    FlyClient,
    FlyClientError,
    FlyCommandFailed,
)
from apps.api.app.services.actuators.fly.specs import FlyDeployResult, FlyDeploySpec

__all__ = [
    "FlyActionError",
    "FlyBinaryMissing",
    "FlyClient",
    "FlyClientError",
    "FlyCommandFailed",
    "FlyDeployResult",
    "FlyDeploySpec",
    "FlyRollbackImpossibleError",
    "deploy",
    "rollback_deploy",
]
