"""Typed payloads for the ``fly.*`` action family.

All fly actions are content-addressed: the image is pinned by full
sha256 digest, never by a mutable tag like ``latest``. Validators in this
module enforce that at the pydantic boundary, so an LLM agent can never
propose a deploy of an unresolved tag.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_HEX = frozenset("0123456789abcdef")
_SHA256_PREFIX = "sha256:"
_SHA256_HEX_LEN = 64


class FlyDeploySpec(BaseModel):
    """Payload for ``action_type=fly.deploy``.

    The ``app`` field is a ``Literal`` enum of the two Fly apps Quorum
    owns — we can never accidentally deploy into something else. The
    ``image_digest`` must be a ``sha256:<64 hex>`` string; any tag form
    (``latest``, ``main``, a branch name) is rejected here.
    """

    model_config = ConfigDict(extra="forbid")

    app: Literal["quorum-staging", "quorum-prod"]
    image_digest: str = Field(
        min_length=len(_SHA256_PREFIX) + _SHA256_HEX_LEN,
        max_length=len(_SHA256_PREFIX) + _SHA256_HEX_LEN,
        description="Full content-addressed digest — e.g. 'sha256:abc...'",
    )
    strategy: Literal["rolling", "bluegreen", "immediate"] = "rolling"

    @field_validator("image_digest")
    @classmethod
    def digest_must_be_sha256(cls, value: str) -> str:
        if not value.startswith(_SHA256_PREFIX):
            raise ValueError(f"image_digest must start with '{_SHA256_PREFIX}'")
        hex_part = value[len(_SHA256_PREFIX) :]
        if len(hex_part) != _SHA256_HEX_LEN:
            raise ValueError(
                f"image_digest hex part must be {_SHA256_HEX_LEN} chars, got {len(hex_part)}"
            )
        if any(c not in _HEX for c in hex_part):
            raise ValueError("image_digest hex part must be lowercase hex")
        return value


class FlyDeployResult(BaseModel):
    """Captured outcome of a deploy — written into the execution record.

    ``previous_image_digest`` is the digest the app was running *before*
    this deploy; required by the rollback path, which re-deploys it.
    Empty string on the first deploy (no prior release).
    """

    model_config = ConfigDict(extra="forbid")

    app: str
    released_image_digest: str
    previous_image_digest: str = ""
    release_id: str = ""
    strategy: str = "rolling"
