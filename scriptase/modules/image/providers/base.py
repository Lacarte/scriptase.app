"""Storyboard Provider Base Contract — Provider Contract v2 (step 14.2).

Storyboard generation is asynchronous and multi-unit for every provider, so the
interface is the shared `AsyncMediaProvider` shape from step 14.1: `submit`
returns a `JobHandle`, `poll` reports a `JobStatus`, and the media-job service
owns the deadline, cadence, cancellation, progress, retry, and aggregation.

Two changes from the v1 shape this replaces:

  * `submit(project_id, scenes, settings, on_progress)` becomes
    `submit(request, invocation)`. The three loose arguments were why every
    caller had to know which provider it was talking to — `settings` was
    provider-shaped, `scenes` had two incompatible spellings, and `on_progress`
    duplicated `ProviderInvocation.progress`;
  * `poll(job_id, settings)` becomes `poll(job_id, invocation)`, so a poll can
    observe cancellation and report progress like any other call.

Providers own only remote/local generation mechanics. The manifest, per-scene
metadata, thumbnails, and the watermark pass belong to `scriptase.modules.image.jobs`
and are applied identically whichever provider produced the frame.

`JobHandle`, `JobStatus`, and `SceneResult` are re-exported so existing
`from scriptase.modules.image.providers.base import JobHandle` imports keep resolving;
`SceneResult` is the media-neutral `UnitResult` (§33.1).
"""

from abc import ABC, abstractmethod

from scriptase.providers.invocation import ProviderInvocation
from scriptase.providers.jobs import (  # noqa: F401  (re-exported)
    JobHandle,
    JobStatus,
    SceneResult,
    UnitResult,
)
from scriptase.modules.image.providers.contract import (  # noqa: F401  (re-exported)
    StoryboardRequest,
    StoryboardResultPayload,
)


class StoryboardProvider(ABC):
    """Base class for all storyboard providers (contracts.md §32.4, §33)."""

    @abstractmethod
    def submit(
        self, request: StoryboardRequest, invocation: ProviderInvocation
    ) -> JobHandle:
        """Start a storyboard job and return its handle.

        The handle's `job_id` is the public identity; the shipped providers keep
        using the project ID, so existing status URLs and job records stay
        valid. Durable provider settings arrive on `invocation.settings`, per-run
        node or request values on `invocation.options`.
        """

    @abstractmethod
    def poll(self, job_id: str, invocation: ProviderInvocation) -> JobStatus:
        """Report the current state of a submitted job.

        A provider that pushes its results still implements this: it is the
        §33.3 watchdog, and answering from the manifest is what stops a lost
        callback hanging the job for a whole deadline.
        """

    def cancel_job(self, job_id: str, invocation: ProviderInvocation) -> None:
        """Best-effort remote cancellation. Optional; the default is a no-op."""

    def generate_one(
        self, request: StoryboardRequest, invocation: ProviderInvocation
    ) -> SceneResult:
        """Generate a single scene synchronously. Optional.

        Providers declaring `single_scene` may implement this; the legacy
        single-image route reaches them through `submit` with a one-scene
        request instead, so nothing depends on it today.
        """
        raise NotImplementedError(
            f"generate_one is not supported by {self.__class__.__name__}"
        )

    def shutdown(self) -> None:
        """Clean up resources. Called on app shutdown."""


__all__ = [
    "JobHandle",
    "JobStatus",
    "SceneResult",
    "StoryboardProvider",
    "StoryboardRequest",
    "StoryboardResultPayload",
    "UnitResult",
]
