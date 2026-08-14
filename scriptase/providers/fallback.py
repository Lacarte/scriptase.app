"""Fallback chain execution and per-unit provenance (step 8.3).

Activates the ``fallback_policies`` chains persisted at step 3.3. A primary
instance failure falls through to the next ordered instance; multi-unit runs
may produce units from different providers. When a unit's producer differs
from the envelope, the unit carries sparse overrides (seed / request_id /
model_revision / provider_id / provider_instance_id / selection_reason).
Absent fields inherit envelope provenance (contracts.md §1.7 / §2).

``selection_reason`` uses the frozen vocabulary:
  ``request | node_config | settings | channel | default | fallback_after:<id>``

This module never invents seed / request_id / model_revision — it only harvests
values the platform already lifts from result metadata and options.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Mapping, Sequence

from scriptase.providers.errors import (
    PROVIDER_UNIT_FAILED,
    ProviderCancelled,
    ProviderError,
)
from scriptase.providers.results import (
    FAILED,
    PARTIAL,
    SUCCEEDED,
    UNIT_FAILED,
    UNIT_SUCCEEDED,
    Provenance,
    ProviderResult,
    UnitResult,
    derive_status,
    extract_reproducibility,
)
from scriptase.providers.selection import (
    fallback_policy_from_snapshot,
    normalize_fallback_policy,
    ordered_fallback_ids,
)


FALLBACK_AFTER_PREFIX = "fallback_after:"

# Primary-rung reasons that are not fallback. Anything starting with
# FALLBACK_AFTER_PREFIX is a chain advance.
PRIMARY_SELECTION_REASONS = frozenset(
    {"request", "node_config", "settings", "channel", "default", "selection"}
)


# ---------------------------------------------------------------------------
# selection_reason vocabulary
# ---------------------------------------------------------------------------


def format_fallback_reason(previous_instance_id: str) -> str:
    """``fallback_after:<instance_id>`` — why this attempt ran."""
    previous = str(previous_instance_id or "").strip()
    if not previous:
        raise ValueError("fallback_after requires a previous instance id")
    return f"{FALLBACK_AFTER_PREFIX}{previous}"


def parse_fallback_reason(reason: str | None) -> str | None:
    """Return the previous instance id when *reason* is ``fallback_after:…``."""
    text = str(reason or "").strip()
    if not text.startswith(FALLBACK_AFTER_PREFIX):
        return None
    previous = text[len(FALLBACK_AFTER_PREFIX) :].strip()
    return previous or None


def is_fallback_reason(reason: str | None) -> bool:
    return parse_fallback_reason(reason) is not None


def selection_reason_for_index(
    index: int,
    *,
    primary_reason: str = "channel",
    chain: Sequence[str],
) -> str:
    """Reason for chain position *index* (0 = primary)."""
    if index <= 0:
        reason = str(primary_reason or "default").strip() or "default"
        return reason
    previous = chain[index - 1] if index - 1 < len(chain) else ""
    return format_fallback_reason(previous)


# ---------------------------------------------------------------------------
# Chain resolution
# ---------------------------------------------------------------------------


def resolve_execution_chain(
    domain: str,
    *,
    primary_instance_id: str,
    fallback_policy: Any = None,
    channel_snapshot: Mapping[str, Any] | None = None,
    stage: str | None = None,
    channel_settings: Mapping[str, Any] | None = None,
) -> list[str]:
    """Ordered instance ids to try: primary first, then configured fallbacks.

    Sources for the policy (first non-empty wins):

    1. Explicit ``fallback_policy``
    2. ``channel_snapshot.fallback_policies[stage|domain]``
    3. ``channel_settings.fallback_policies[stage|domain]`` (flat Job blob)

    When no fallbacks are configured the chain is ``[primary]`` alone so
    callers can treat ``len(chain) == 1`` as "no fallback".
    """
    primary = str(primary_instance_id or "").strip()
    if not primary:
        return []

    policy = normalize_fallback_policy(fallback_policy)
    stage_key = (stage or domain or "").strip()

    if policy is None and channel_snapshot is not None:
        policy = fallback_policy_from_snapshot(channel_snapshot, stage_key)
        if policy is None and stage_key != domain:
            policy = fallback_policy_from_snapshot(channel_snapshot, domain)

    if policy is None and isinstance(channel_settings, Mapping):
        policies = channel_settings.get("fallback_policies")
        if isinstance(policies, Mapping):
            raw = policies.get(stage_key)
            if raw is None and stage_key != domain:
                raw = policies.get(domain)
            policy = normalize_fallback_policy(raw)

    ordered = ordered_fallback_ids(policy)
    if not ordered:
        return [primary]

    # Start at the selected primary when it appears in the policy; otherwise
    # prepend it so a node override still gets the policy's fallbacks after it.
    if primary in ordered:
        start = ordered.index(primary)
        return list(ordered[start:])
    return [primary, *[iid for iid in ordered if iid != primary]]


# ---------------------------------------------------------------------------
# Per-unit provenance (contracts.md §1.7 / §2)
# ---------------------------------------------------------------------------


def harvest_unit_reproducibility(
    unit: UnitResult,
    *,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Lift seed / request_id / model_revision for one unit without inventing."""
    meta = dict(unit.metadata or {})
    # Prefer already-stamped sparse fields, then unit metadata, then options.
    seed = unit.seed
    if seed is None:
        seed = extract_reproducibility(metadata=meta, options=options).get("seed")
    request_id = unit.request_id or ""
    model_revision = unit.model_revision or ""
    if not request_id or not model_revision or seed is None:
        lifted = extract_reproducibility(metadata=meta, options=options)
        if seed is None:
            seed = lifted["seed"]
        if not request_id:
            request_id = lifted["request_id"]
        if not model_revision:
            model_revision = lifted["model_revision"]
    return {
        "seed": seed,
        "request_id": request_id,
        "model_revision": model_revision,
    }


def stamp_unit_producer(
    unit: UnitResult,
    *,
    provider_id: str = "",
    provider_instance_id: str = "",
    selection_reason: str = "",
    options: Mapping[str, Any] | None = None,
    stamp_identity: bool = True,
) -> UnitResult:
    """Return *unit* with sparse producer / reproducibility fields filled.

    Identity fields (provider_id / provider_instance_id / selection_reason) are
    written when ``stamp_identity`` is True — used for units whose producer
    differs from the envelope (fallback). Reproducibility fields are always
    harvested from metadata when the sparse slots are empty.
    """
    repro = harvest_unit_reproducibility(unit, options=options)
    return replace(
        unit,
        seed=repro["seed"] if unit.seed is None else unit.seed,
        request_id=unit.request_id or repro["request_id"],
        model_revision=unit.model_revision or repro["model_revision"],
        provider_id=(
            str(provider_id or unit.provider_id or "")
            if stamp_identity
            else unit.provider_id
        ),
        provider_instance_id=(
            str(provider_instance_id or unit.provider_instance_id or "")
            if stamp_identity
            else unit.provider_instance_id
        ),
        selection_reason=(
            str(selection_reason or unit.selection_reason or "")
            if stamp_identity
            else unit.selection_reason
        ),
    )


def stamp_units_for_attempt(
    units: Sequence[UnitResult],
    *,
    provider_id: str,
    provider_instance_id: str,
    selection_reason: str,
    options: Mapping[str, Any] | None = None,
    only_indices: Iterable[int] | None = None,
    stamp_identity: bool = True,
) -> list[UnitResult]:
    """Stamp every (or selected) unit produced by one attempt."""
    wanted = None if only_indices is None else {int(i) for i in only_indices}
    stamped: list[UnitResult] = []
    for unit in units:
        if wanted is not None and unit.unit_index not in wanted:
            stamped.append(unit)
            continue
        stamped.append(
            stamp_unit_producer(
                unit,
                provider_id=provider_id,
                provider_instance_id=provider_instance_id,
                selection_reason=selection_reason,
                options=options,
                stamp_identity=stamp_identity,
            )
        )
    return stamped


def effective_unit_provenance(
    unit: UnitResult,
    envelope: Provenance | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Resolve one unit's producer identity + reproducibility.

    Sparse unit overrides win; otherwise the unit inherits the envelope.
    Never invents seed / request_id / model_revision.
    """
    if isinstance(envelope, Provenance):
        env = envelope.to_dict()
    elif isinstance(envelope, Mapping):
        env = dict(envelope)
    else:
        env = {}

    seed = unit.seed if unit.seed is not None else env.get("seed")
    request_id = unit.request_id or env.get("request_id") or ""
    model_revision = unit.model_revision or env.get("model_revision") or ""
    provider_id = unit.provider_id or env.get("provider_id") or ""
    provider_instance_id = (
        unit.provider_instance_id or env.get("provider_instance_id") or ""
    )
    selection_reason = unit.selection_reason or env.get("selection_reason") or ""

    # Last-chance harvest from unit metadata when still empty.
    if seed is None or not request_id or not model_revision:
        lifted = harvest_unit_reproducibility(unit)
        if seed is None:
            seed = lifted["seed"]
        if not request_id:
            request_id = lifted["request_id"]
        if not model_revision:
            model_revision = lifted["model_revision"]

    return {
        "unit_index": unit.unit_index,
        "state": unit.state,
        "provider_id": provider_id,
        "provider_instance_id": provider_instance_id,
        "selection_reason": selection_reason,
        "seed": seed,
        "request_id": request_id,
        "model_revision": model_revision,
        "artifact_refs": list(unit.artifact_refs),
    }


def apply_envelope_inheritance(
    units: Sequence[UnitResult],
    envelope: Provenance,
) -> list[UnitResult]:
    """Strip identity overrides that merely duplicate the envelope (sparse).

    Units whose producer matches the envelope keep only reproducibility
    overrides that differ; pure duplicates stay sparse-empty so inheritance is
    the single source of truth for ordinary single-provider runs.
    """
    out: list[UnitResult] = []
    for unit in units:
        provider_id = unit.provider_id
        provider_instance_id = unit.provider_instance_id
        selection_reason = unit.selection_reason
        if provider_id and provider_id == envelope.provider_id:
            provider_id = ""
        if (
            provider_instance_id
            and provider_instance_id == envelope.provider_instance_id
        ):
            provider_instance_id = ""
        if selection_reason and selection_reason == envelope.selection_reason:
            selection_reason = ""
        seed = unit.seed
        if seed is not None and seed == envelope.seed:
            seed = None
        request_id = unit.request_id
        if request_id and request_id == envelope.request_id:
            request_id = ""
        model_revision = unit.model_revision
        if model_revision and model_revision == envelope.model_revision:
            model_revision = ""
        out.append(
            replace(
                unit,
                seed=seed,
                request_id=request_id,
                model_revision=model_revision,
                provider_id=provider_id,
                provider_instance_id=provider_instance_id,
                selection_reason=selection_reason,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Fallback execution
# ---------------------------------------------------------------------------


@dataclass
class FallbackAttempt:
    """One try against one instance in the chain."""

    instance_id: str
    provider_id: str
    selection_reason: str
    previous_instance_id: str | None = None
    result: ProviderResult | None = None
    error: ProviderError | None = None
    unit_indices: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "instance_id": self.instance_id,
            "provider_id": self.provider_id,
            "selection_reason": self.selection_reason,
            "previous_instance_id": self.previous_instance_id,
            "unit_indices": list(self.unit_indices),
        }
        if self.error is not None:
            payload["error"] = {
                "code": self.error.code,
                "message": self.error.message,
                "retryable": self.error.retryable,
            }
        if self.result is not None:
            payload["status"] = self.result.status
            payload["units"] = [unit.to_dict() for unit in self.result.units]
        return payload


@dataclass
class FallbackRunRecord:
    """Authoritative record of a fallback-aware provider run.

    ``result`` is the merged envelope. ``units_effective`` is the done-when
    surface: every unit with resolved instance / seed / model_revision.
    """

    domain: str
    chain: list[str]
    attempts: list[FallbackAttempt] = field(default_factory=list)
    result: ProviderResult = field(default_factory=ProviderResult)

    def units_effective(self) -> list[dict[str, Any]]:
        return [
            effective_unit_provenance(unit, self.result.provenance)
            for unit in self.result.units
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "chain": list(self.chain),
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "result": self.result.to_dict(),
            "units_effective": self.units_effective(),
        }


# run_one(instance_id, selection_reason, prior_succeeded_units) -> ProviderResult
RunOne = Callable[
    [str, str, Sequence[UnitResult]],
    ProviderResult,
]

# resolve_type(instance_id) -> provider type id (defaults to instance_id)
ResolveType = Callable[[str], str]


def _succeeded_units(units: Sequence[UnitResult]) -> list[UnitResult]:
    return [unit for unit in units if unit.state == UNIT_SUCCEEDED]


def _failed_or_missing(
    units: Sequence[UnitResult],
    *,
    expected_count: int | None = None,
) -> list[int]:
    succeeded = {unit.unit_index for unit in units if unit.state == UNIT_SUCCEEDED}
    if expected_count is not None and expected_count > 0:
        return [i for i in range(expected_count) if i not in succeeded]
    return [
        unit.unit_index
        for unit in units
        if unit.state != UNIT_SUCCEEDED
    ]


def _merge_units(
    prior: Sequence[UnitResult],
    fresh: Sequence[UnitResult],
) -> list[UnitResult]:
    """Succeeded priors win; fresh results fill the rest (D34-compatible)."""
    from scriptase.providers.media_jobs import merge_prior_units

    return list(merge_prior_units(prior, fresh))


def _is_cancel(exc: BaseException) -> bool:
    if isinstance(exc, ProviderCancelled):
        return True
    if isinstance(exc, ProviderError) and exc.code == "CANCELLED":
        return True
    return False


def _should_advance(exc: ProviderError | None, *, has_more: bool) -> bool:
    """Whether to try the next chain member after *exc* or a partial result."""
    if not has_more:
        return False
    if exc is None:
        return True  # partial success path
    if _is_cancel(exc):
        return False
    # Auth / not-configured / invalid request are instance-specific; still
    # fall through so a misconfigured primary does not block a healthy backup.
    # Cancellation is the only hard stop above.
    return True


def run_with_fallback(
    *,
    domain: str,
    chain: Sequence[str],
    run_one: RunOne,
    multi_unit: bool = False,
    primary_selection_reason: str = "channel",
    resolve_type: ResolveType | None = None,
    expected_unit_count: int | None = None,
    options_for: Callable[[str], Mapping[str, Any]] | None = None,
) -> FallbackRunRecord:
    """Execute *chain* until every unit succeeds or the chain is exhausted.

    Parameters
    ----------
    domain:
        Provider domain id (image, video, tts, …).
    chain:
        Ordered instance ids from :func:`resolve_execution_chain`.
    run_one:
        ``(instance_id, selection_reason, prior_succeeded_units) -> ProviderResult``.
        May raise :class:`ProviderError`. For multi-unit retries, *prior*
        succeeded units must not be re-requested; the caller filters the
        request (see :func:`scriptase.providers.media_jobs.filter_request_units`).
    multi_unit:
        When True, partial success reuses succeeded units and only re-runs the
        rest on the next instance. When False, a raised error falls through
        and the next instance replaces the whole result.
    primary_selection_reason:
        Provenance reason for chain index 0.
    resolve_type:
        Map instance id → provider type id (defaults to identity).
    expected_unit_count:
        Optional total unit count for multi-unit runs (when the first attempt
        fails before reporting units).
    options_for:
        Optional ``instance_id -> options`` used when harvesting seed from
        call-time options.
    """
    domain_id = str(domain or "").strip()
    ordered = [str(i).strip() for i in chain if str(i).strip()]
    if not ordered:
        raise ProviderError(
            "PROVIDER_NOT_FOUND",
            "No provider instance is available for fallback execution",
            domain=domain_id,
        )

    type_of: ResolveType = resolve_type or (lambda iid: iid)
    attempts: list[FallbackAttempt] = []
    accumulated: list[UnitResult] = []
    final_result: ProviderResult | None = None
    last_error: ProviderError | None = None
    # Envelope is anchored on the first attempt that produces any success, or
    # the primary attempt when the whole chain fails (for diagnostics).
    envelope_provenance: Provenance | None = None
    envelope_instance_id: str = ordered[0]

    for index, instance_id in enumerate(ordered):
        reason = selection_reason_for_index(
            index, primary_reason=primary_selection_reason, chain=ordered
        )
        previous = ordered[index - 1] if index > 0 else None
        provider_type = str(type_of(instance_id) or instance_id)
        prior = list(accumulated) if multi_unit else []
        attempt = FallbackAttempt(
            instance_id=instance_id,
            provider_id=provider_type,
            selection_reason=reason,
            previous_instance_id=previous,
            unit_indices=tuple(
                _failed_or_missing(prior, expected_count=expected_unit_count)
                if multi_unit and prior
                else ()
            ),
        )

        try:
            result = run_one(instance_id, reason, prior)
        except ProviderCancelled:
            raise
        except ProviderError as exc:
            if _is_cancel(exc):
                raise
            attempt.error = exc
            attempts.append(attempt)
            last_error = exc
            has_more = index + 1 < len(ordered)
            if multi_unit and isinstance(exc.details, Mapping):
                # All-units-failed still may carry unit diagnostics.
                raw_units = exc.details.get("units") or []
                recovered: list[UnitResult] = []
                for raw in raw_units:
                    if isinstance(raw, UnitResult):
                        recovered.append(raw)
                    elif isinstance(raw, Mapping):
                        recovered.append(UnitResult.from_dict(raw))
                if recovered:
                    opts = options_for(instance_id) if options_for else None
                    # Identity only when this attempt is a fallback rung, or
                    # when multi-instance already mixed — primary units that
                    # failed do not need identity stamps.
                    stamp_id = is_fallback_reason(reason) or bool(prior)
                    stamped = stamp_units_for_attempt(
                        recovered,
                        provider_id=provider_type,
                        provider_instance_id=instance_id,
                        selection_reason=reason,
                        options=opts,
                        stamp_identity=stamp_id,
                    )
                    # Keep only succeeded (if any leaked) into accumulated.
                    accumulated = _merge_units(accumulated, stamped)
            if _should_advance(exc, has_more=has_more):
                continue
            raise
        except BaseException:
            # Non-provider exceptions are the caller's boundary's job; re-raise.
            raise

        opts = options_for(instance_id) if options_for else None
        # Stamp identity on units when this attempt is a fallback, or when we
        # already have prior units from another instance (mixed run).
        stamp_id = is_fallback_reason(reason) or bool(prior)
        stamped_units = stamp_units_for_attempt(
            result.units,
            provider_id=provider_type,
            provider_instance_id=instance_id,
            selection_reason=reason,
            options=opts,
            stamp_identity=stamp_id,
        )
        # Always harvest reproducibility onto units (even primary) so the
        # done-when surface can show seed / model_revision per unit.
        stamped_units = stamp_units_for_attempt(
            stamped_units,
            provider_id=provider_type,
            provider_instance_id=instance_id,
            selection_reason=reason,
            options=opts,
            stamp_identity=False,
        )

        if multi_unit:
            accumulated = _merge_units(accumulated, stamped_units)
            result.units = list(accumulated)
            if result.units:
                derived = derive_status(result.units)
                if derived in {SUCCEEDED, PARTIAL, FAILED}:
                    result.status = derived
        else:
            accumulated = list(stamped_units)
            result.units = list(stamped_units)

        # Fill empty provider identity on the envelope from this attempt when
        # the runner did not (media jobs historically omit provenance).
        if result.provenance.provider_id == "" and result.provenance.domain == "":
            result.provenance = replace(
                result.provenance,
                domain=domain_id or result.domain,
                provider_id=provider_type,
                provider_instance_id=instance_id,
                selection_reason=reason,
            )
        elif not result.provenance.provider_instance_id:
            result.provenance = replace(
                result.provenance,
                provider_instance_id=instance_id,
                selection_reason=result.provenance.selection_reason or reason,
            )

        attempt.result = result
        attempts.append(attempt)
        final_result = result
        last_error = None

        # Anchor envelope on the first attempt that produced any success.
        produced = _succeeded_units(result.units if multi_unit else stamped_units)
        if produced and envelope_provenance is None:
            envelope_provenance = result.provenance
            envelope_instance_id = instance_id
        elif envelope_provenance is None and index == 0:
            envelope_provenance = result.provenance
            envelope_instance_id = instance_id

        if multi_unit:
            pending = _failed_or_missing(
                accumulated, expected_count=expected_unit_count
            )
            if not pending and _succeeded_units(accumulated):
                break
            has_more = index + 1 < len(ordered)
            if pending and _should_advance(None, has_more=has_more):
                continue
            break
        else:
            # Single-shot: success ends the chain.
            if result.status == SUCCEEDED:
                break
            has_more = index + 1 < len(ordered)
            if result.status in {FAILED, PARTIAL} and _should_advance(
                None, has_more=has_more
            ):
                continue
            break

    if final_result is None:
        # Entire chain raised before returning a result.
        if last_error is not None:
            raise last_error
        raise ProviderError(
            PROVIDER_UNIT_FAILED,
            "Fallback chain produced no result",
            domain=domain_id,
        )

    # Re-anchor envelope provenance and sparsify unit overrides against it.
    if envelope_provenance is None:
        envelope_provenance = final_result.provenance

    # When the envelope producer is a fallback instance (primary produced
    # nothing), keep its selection_reason so the record shows why.
    final_result.provenance = envelope_provenance
    final_result.provider_id = (
        final_result.provider_id
        or envelope_provenance.provider_id
        or type_of(envelope_instance_id)
    )
    final_result.domain = final_result.domain or domain_id

    if multi_unit and accumulated:
        final_result.units = apply_envelope_inheritance(
            accumulated, envelope_provenance
        )
        # Re-apply identity stamps for units whose producer still differs
        # after inheritance strip — apply_envelope_inheritance already drops
        # matches; units from other instances keep their overrides.
        # Harvest reproducibility once more so seed survives inheritance.
        final_result.units = [
            stamp_unit_producer(
                unit,
                stamp_identity=False,
                options=options_for(unit.provider_instance_id) if options_for and unit.provider_instance_id else None,
            )
            if unit.seed is None
            else unit
            for unit in final_result.units
        ]
        if final_result.units:
            derived = derive_status(final_result.units)
            if derived in {SUCCEEDED, PARTIAL, FAILED}:
                final_result.status = derived
            if derived == FAILED:
                raise ProviderError(
                    PROVIDER_UNIT_FAILED,
                    f"All {len(final_result.units)} units failed",
                    domain=domain_id,
                    provider_id=final_result.provider_id,
                    details={
                        "units": [unit.to_dict() for unit in final_result.units],
                        "fallback_chain": list(ordered),
                        "attempts": [a.to_dict() for a in attempts],
                    },
                )

    return FallbackRunRecord(
        domain=domain_id,
        chain=list(ordered),
        attempts=attempts,
        result=final_result,
    )


def invoke_chain(
    *,
    domain: str,
    chain: Sequence[str],
    call_for: Callable[[str], Callable[[Any], Any]],
    build_invocation_for: Callable[[str, str], Any],
    multi_unit: bool = False,
    primary_selection_reason: str = "channel",
    resolve_type: ResolveType | None = None,
    provider_version_for: Callable[[str], str] | None = None,
    contract_version_for: Callable[[str], int] | None = None,
    settings_version: int = 0,
    expected_unit_count: int | None = None,
) -> FallbackRunRecord:
    """Run a fallback chain through :func:`scriptase.providers.boundary.invoke`.

    ``call_for(instance_id)`` returns the provider callable
    ``(invocation) -> result``. ``build_invocation_for(instance_id, reason)``
    returns a :class:`ProviderInvocation` with identity already set.
    """
    from scriptase.providers.boundary import invoke

    def run_one(
        instance_id: str,
        selection_reason: str,
        _prior: Sequence[UnitResult],
    ) -> ProviderResult:
        invocation = build_invocation_for(instance_id, selection_reason)
        # Ensure invocation carries the chain reason / instance even if the
        # builder ignored them.
        if getattr(invocation, "selection_reason", None) != selection_reason or (
            getattr(invocation, "provider_instance_id", None) != instance_id
        ):
            invocation = replace(
                invocation,
                selection_reason=selection_reason,
                provider_instance_id=instance_id,
            )
        call = call_for(instance_id)
        version = (
            provider_version_for(instance_id) if provider_version_for else ""
        )
        contract = (
            contract_version_for(instance_id) if contract_version_for else 1
        )
        return invoke(
            call,
            invocation,
            provider_version=version,
            contract_version=contract,
            settings_version=settings_version,
        )

    return run_with_fallback(
        domain=domain,
        chain=chain,
        run_one=run_one,
        multi_unit=multi_unit,
        primary_selection_reason=primary_selection_reason,
        resolve_type=resolve_type,
        expected_unit_count=expected_unit_count,
    )


__all__ = [
    "FALLBACK_AFTER_PREFIX",
    "PRIMARY_SELECTION_REASONS",
    "FallbackAttempt",
    "FallbackRunRecord",
    "apply_envelope_inheritance",
    "effective_unit_provenance",
    "format_fallback_reason",
    "harvest_unit_reproducibility",
    "invoke_chain",
    "is_fallback_reason",
    "parse_fallback_reason",
    "resolve_execution_chain",
    "run_with_fallback",
    "selection_reason_for_index",
    "stamp_unit_producer",
    "stamp_units_for_attempt",
]
