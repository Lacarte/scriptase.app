"""Optional image dependency for video — step 6.2 / product §7.4.

Video nodes must not assume every provider requires an image. Routing is
capability-based:

* storyboard input present → prefer ``image_to_video`` (visual consistency)
* storyboard input absent  → require ``text_to_video`` (Scene Director prompts only)

The default full-video template still wires Storyboard → Animator. A workflow
with no image node is valid when the selected video provider grants
``text_to_video``.
"""

from __future__ import annotations

from typing import Any, Mapping

IMAGE_TO_VIDEO = "image_to_video"
TEXT_TO_VIDEO = "text_to_video"

# Motion modes used on the adapter path (and recorded in failure details).
MOTION_MODES = frozenset({IMAGE_TO_VIDEO, TEXT_TO_VIDEO})


def storyboard_is_present(inputs: Mapping[str, Any] | None) -> bool:
    """True when the animator received a connected storyboard port payload.

    The scheduler only puts a port into ``inputs`` when an edge delivered a
    value, so absence means "no image node / no edge". An empty/null payload is
    treated as absent so a dangling optional edge cannot force image_to_video.
    """
    if not isinstance(inputs, Mapping):
        return False
    if "storyboard" not in inputs:
        return False
    payload = inputs.get("storyboard")
    if payload is None:
        return False
    if isinstance(payload, Mapping) and not payload:
        return False
    return True


def resolve_motion_mode(
    *,
    has_storyboard: bool,
    capabilities: Mapping[str, Any] | None,
) -> str:
    """Return the motion mode the selected provider must run under.

    Raises ``ValueError`` with a stable ``code`` attribute when the provider
    cannot satisfy the graph shape (no silent provider substitution).
    """
    caps = capabilities if isinstance(capabilities, Mapping) else {}
    has_i2v = caps.get(IMAGE_TO_VIDEO) is True
    has_t2v = caps.get(TEXT_TO_VIDEO) is True

    if has_storyboard:
        # Prefer image_to_video for visual consistency when the provider can
        # consume stills; a text_to_video-only provider may still run and simply
        # ignore the storyboard edge (prompts come from Scene Director).
        if has_i2v:
            return IMAGE_TO_VIDEO
        if has_t2v:
            return TEXT_TO_VIDEO
        raise _capability_error(
            code="PROVIDER_REQUEST_INVALID",
            message=(
                "The selected video provider supports neither image_to_video "
                "nor text_to_video"
            ),
            required=IMAGE_TO_VIDEO,
            has_storyboard=True,
            capabilities=caps,
        )

    # No storyboard: prompt-only path. image_to_video-only providers cannot run.
    if has_t2v:
        return TEXT_TO_VIDEO
    raise _capability_error(
        code="PROVIDER_REQUEST_INVALID",
        message=(
            "No storyboard images are connected; the selected video provider "
            "requires image_to_video. Connect a Storyboard node, or select a "
            "text_to_video provider"
        ),
        required=TEXT_TO_VIDEO,
        has_storyboard=False,
        capabilities=caps,
    )


def required_capability_for_graph(*, has_storyboard: bool) -> str:
    """Capability the graph shape implies (for validation / selector queries).

    When storyboard is present the preferred capability is image_to_video; when
    absent the graph *requires* text_to_video.
    """
    return IMAGE_TO_VIDEO if has_storyboard else TEXT_TO_VIDEO


class VideoCapabilityError(ValueError):
    """Provider cannot satisfy the graph's image dependency shape."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


def _capability_error(
    *,
    code: str,
    message: str,
    required: str,
    has_storyboard: bool,
    capabilities: Mapping[str, Any],
) -> VideoCapabilityError:
    granted = sorted(
        key for key, value in capabilities.items() if value is True
    )
    return VideoCapabilityError(
        code,
        message,
        details={
            "required_capability": required,
            "has_storyboard": has_storyboard,
            "granted_capabilities": granted,
        },
    )


__all__ = [
    "IMAGE_TO_VIDEO",
    "TEXT_TO_VIDEO",
    "MOTION_MODES",
    "VideoCapabilityError",
    "required_capability_for_graph",
    "resolve_motion_mode",
    "storyboard_is_present",
]
