"""LLM virality judge — a semantic second opinion behind an n8n webhook.

Owns the *transport and translation*, never new arithmetic: it POSTs the script
to the configured n8n/OpenRouter webhook, asks the model to rate the same six
frozen dimensions the deterministic scorer uses, and folds the reply back into
the frozen :class:`ViralScore`. The dimension ids, weights, and band floors are
the domain contract — a judge that disagrees still fills in the same breakdown —
so its output is directly comparable to the deterministic score.

The webhook body may embed third-party model text; no raw body is ever copied
into an error (§34.4). Non-200 failures are classified into the shared provider
codes (billing / auth / rate / bad request) just like the script providers.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

import requests as http_requests

from scriptase.modules.viral.models import (
    DIMENSION_IDS,
    DIMENSION_WEIGHTS,
    DimensionScore,
    ScoreReason,
    ViralScore,
    band_for,
)
from scriptase.modules.viral.providers.base import ViralProvider
from scriptase.modules.viral.providers.contract import (
    ViralRequest,
    ViralResultPayload,
)
from scriptase.providers.errors import (
    PROVIDER_REQUEST_INVALID,
    PROVIDER_RESPONSE_MALFORMED,
    PROVIDER_TIMEOUT,
    PROVIDER_TRANSPORT_FAILED,
    ProviderError,
    classify_webhook_error,
)
from scriptase.shared.security import is_safe_webhook_url
from scriptase.shared.webhooks import WebhookResponseError, call_webhook

_DOMAIN = "viral"
_PROVIDER_ID = "llm_judge"

# Bump when the prompt, the parsing, or the dimension mapping changes, so a
# stored LLM score is never silently compared against different arithmetic.
_SCORER_VERSION = 1


def _resolve_webhook_url(settings: Mapping[str, Any] | None) -> str:
    """Instance setting wins; fall back to the env var (never the reverse)."""
    from config import N8N_VIRALITY_WEBHOOK_URL

    configured = str((settings or {}).get("webhook_url") or "").strip()
    return configured or N8N_VIRALITY_WEBHOOK_URL


def _clamp01(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _build_score(raw: Mapping[str, Any]) -> ViralScore:
    """Fold the model's JSON reply into the frozen ViralScore.

    Expected reply shape (validated by the n8n workflow before it responds):
        {"dimensions": {"hook": {"score": 0.8, "reason": "..."}, ...},
         "summary": "..."}
    A missing dimension scores 0 rather than raising — a partial judgment is
    still a comparable one, and the reason records that it was absent.
    """
    dims: list[DimensionScore] = []
    total = 0.0
    reported = raw.get("dimensions") if isinstance(raw.get("dimensions"), Mapping) else {}
    for name in DIMENSION_IDS:
        entry = reported.get(name) if isinstance(reported, Mapping) else None
        weight = DIMENSION_WEIGHTS[name]
        if isinstance(entry, Mapping):
            value = _clamp01(entry.get("score"))
            detail = str(entry.get("reason") or "").strip()[:400]
            code = "llm_dimension"
        elif entry is not None:  # a bare number is acceptable too
            value = _clamp01(entry)
            detail = ""
            code = "llm_dimension"
        else:
            value = 0.0
            detail = "not scored by the judge"
            code = "llm_dimension_missing"
        points = round(value * weight * 100, 4)
        total += points
        reasons = [ScoreReason(
            code=code,
            impact="positive" if value >= 0.5 else "negative",
            detail={"note": detail} if detail else {},
        )]
        dims.append(DimensionScore(id=name, score=value, weight=weight, points=points, reasons=reasons))

    score = max(0, min(100, round(total)))
    metrics: dict[str, Any] = {}
    summary = str(raw.get("summary") or "").strip()
    if summary:
        metrics["summary"] = summary[:1000]
    if raw.get("model"):
        metrics["model"] = str(raw.get("model"))[:120]
    return ViralScore(
        scorer=_PROVIDER_ID,
        scorer_version=_SCORER_VERSION,
        score=score,
        band=band_for(score),
        dimensions=dims,
        metrics=metrics,
    )


class LlmJudgeViralProvider(ViralProvider):
    """Scores a script's virality with an LLM behind an n8n webhook."""

    def score(
        self,
        request: ViralRequest,
        *,
        settings: Mapping[str, Any] | None = None,
    ) -> ViralResultPayload:
        if not request.has_content:
            raise ProviderError(
                PROVIDER_REQUEST_INVALID,
                "There is no script to score",
                domain=_DOMAIN,
                provider_id=_PROVIDER_ID,
            )

        webhook_url = _resolve_webhook_url(settings)
        allow_private = os.environ.get("STS_ALLOW_PRIVATE_WEBHOOKS", "true").lower() == "true"
        if not is_safe_webhook_url(webhook_url, allow_private=allow_private):
            raise ProviderError(
                PROVIDER_REQUEST_INVALID,
                "The virality webhook URL is not allowed",
                domain=_DOMAIN,
                provider_id=_PROVIDER_ID,
            )

        payload = {
            "job_id": request.job_id,
            "sections": request.sections,
            "story_text": request.story_text,
            "target_duration": request.target_duration,
            # The judge must rate exactly these, so the two scores align.
            "dimensions": list(DIMENSION_IDS),
        }

        webhook_caller = (settings or {}).get("_webhook_caller") or call_webhook
        try:
            result = webhook_caller(webhook_url, payload, timeout=120, label="Virality judge")
        except http_requests.Timeout as exc:
            raise ProviderError(
                PROVIDER_TIMEOUT, "The virality webhook timed out",
                domain=_DOMAIN, provider_id=_PROVIDER_ID, cause_type=type(exc).__name__,
            ) from exc
        except http_requests.ConnectionError as exc:
            raise ProviderError(
                PROVIDER_TRANSPORT_FAILED, "Could not reach the virality webhook",
                domain=_DOMAIN, provider_id=_PROVIDER_ID, cause_type=type(exc).__name__,
            ) from exc
        except WebhookResponseError as exc:
            code, message = classify_webhook_error(getattr(exc, "status", None), str(exc))
            raise ProviderError(
                code, message, domain=_DOMAIN, provider_id=_PROVIDER_ID,
                cause_type=type(exc).__name__,
            ) from exc
        except RuntimeError as exc:
            raise ProviderError(
                PROVIDER_TRANSPORT_FAILED, "The virality webhook failed after retries",
                domain=_DOMAIN, provider_id=_PROVIDER_ID, cause_type=type(exc).__name__,
            ) from exc

        if not isinstance(result, Mapping) or not result.get("dimensions"):
            raise ProviderError(
                PROVIDER_RESPONSE_MALFORMED,
                "The virality webhook returned no dimension scores",
                domain=_DOMAIN,
                provider_id=_PROVIDER_ID,
            )
        return _build_score(result)


def create() -> LlmJudgeViralProvider:
    """Zero-arg factory required by the provider registry."""
    return LlmJudgeViralProvider()


def validate_settings(settings: dict) -> list[dict]:
    issues: list[dict] = []
    url = str((settings or {}).get("webhook_url") or "").strip()
    if not url:
        return issues
    allow_private = os.environ.get("STS_ALLOW_PRIVATE_WEBHOOKS", "true").lower() == "true"
    if not is_safe_webhook_url(url, allow_private=allow_private):
        issues.append({"field": "webhook_url", "severity": "error", "message": "Unsafe webhook URL"})
    return issues


def health_check(settings: dict) -> dict:
    """Report whether a virality webhook is configured. No request is made."""
    from config import N8N_VIRALITY_WEBHOOK_URL

    configured = bool((settings or {}).get("webhook_url") or N8N_VIRALITY_WEBHOOK_URL)
    return {
        "status": "ok" if configured else "warn",
        "latency_ms": 0,
        "message": (
            "Virality webhook configured" if configured
            else "No virality webhook URL is configured"
        ),
    }
