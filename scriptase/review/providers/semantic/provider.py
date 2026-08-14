"""Semantic review provider — offline structured-issue emitter (step 7.3).

Deterministic heuristics only: no network, no credentials. Proves the review
domain can return structured issues through the standard ``ProviderResult``
envelope and error boundary without framework redesign.

AI-backed reviewers ship as sibling packages under
``scriptase/review/providers/`` and declare the same capability vocabulary.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from scriptase.review.providers.base import ReviewProvider
from scriptase.review.providers.contract import (
    SUBJECT_CAPABILITY,
    ReviewIssueItem,
    ReviewRequest,
    ReviewResultPayload,
)

# Placeholders that never belong in production narration / captions.
_PLACEHOLDER_RE = re.compile(
    r"\b(?:TODO|TBD|FIXME|lorem\s+ipsum|placeholder|test\s+image|"
    r"sample\s+text|xxx)\b",
    re.IGNORECASE,
)

_WORD_RE = re.compile(r"\S+")


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text or "")


def _contains_subject(haystack: str, subject: str) -> bool:
    """Loose subject match: every significant token of subject appears."""
    hay = (haystack or "").casefold()
    tokens = [
        token
        for token in re.findall(r"[a-z0-9']+", (subject or "").casefold())
        if len(token) > 2
    ]
    if not tokens:
        return True
    return all(token in hay for token in tokens)


class SemanticReviewProvider(ReviewProvider):
    """Offline semantic reviewer for text, image, video, and structured subjects."""

    def _confidence(self, settings: Mapping[str, Any]) -> float:
        raw = settings.get("confidence", 0.85)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return 0.85
        return max(0.0, min(1.0, value))

    def _min_words(self, settings: Mapping[str, Any]) -> int:
        raw = settings.get("min_text_words", 8)
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return 8

    def _duration_tolerance(self, settings: Mapping[str, Any]) -> float:
        raw = settings.get("duration_tolerance_s", 1.5)
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            return 1.5

    def _base_issue(
        self,
        request: ReviewRequest,
        *,
        settings: Mapping[str, Any],
        issue_type: str,
        severity: str,
        reason: str,
        suggested_action: str = "regenerate",
        repair_instruction: str = "",
        observed: Mapping[str, Any] | None = None,
        expected: Mapping[str, Any] | None = None,
    ) -> ReviewIssueItem:
        return ReviewIssueItem(
            job_id=request.job_id,
            scene_id=request.scene_id,
            target_node_id=request.target_node_id,
            target_artifact_id=request.target_artifact_id,
            issue_type=issue_type,
            severity=severity,
            confidence=self._confidence(settings),
            reason=reason,
            suggested_action=suggested_action,
            repair_instruction=repair_instruction,
            observed=dict(observed or {}),
            expected=dict(expected or {}),
        )

    def _review_text(
        self, request: ReviewRequest, settings: Mapping[str, Any]
    ) -> list[ReviewIssueItem]:
        issues: list[ReviewIssueItem] = []
        text = request.text or ""
        word_count = len(_words(text))
        min_words = self._min_words(settings)

        if not text.strip():
            issues.append(
                self._base_issue(
                    request,
                    settings=settings,
                    issue_type="script_defect",
                    severity="critical",
                    reason="Reviewed text is empty.",
                    suggested_action="regenerate",
                    repair_instruction="Produce non-empty narration for this unit.",
                    observed={"word_count": 0},
                    expected={"min_words": min_words},
                )
            )
            return issues

        if word_count < min_words:
            issues.append(
                self._base_issue(
                    request,
                    settings=settings,
                    issue_type="script_defect",
                    severity="medium",
                    reason=(
                        f"Text has {word_count} words; minimum expected is "
                        f"{min_words}."
                    ),
                    suggested_action="re-prompt",
                    repair_instruction=(
                        "Expand the narration while preserving tone and subject."
                    ),
                    observed={"word_count": word_count},
                    expected={"min_words": min_words},
                )
            )

        match = _PLACEHOLDER_RE.search(text)
        if match:
            issues.append(
                self._base_issue(
                    request,
                    settings=settings,
                    issue_type="script_defect",
                    severity="high",
                    reason=f"Text contains placeholder language ({match.group(0)!r}).",
                    suggested_action="regenerate",
                    repair_instruction="Remove placeholders; write finished narration.",
                    observed={"placeholder": match.group(0)},
                    expected={"placeholders": False},
                )
            )

        if request.expected_subject and not _contains_subject(
            text, request.expected_subject
        ):
            issues.append(
                self._base_issue(
                    request,
                    settings=settings,
                    issue_type="script_defect",
                    severity="high",
                    reason=(
                        "Narration does not mention the expected subject "
                        f"{request.expected_subject!r}."
                    ),
                    suggested_action="re-prompt",
                    repair_instruction=(
                        f"Keep structure; ensure subject "
                        f"{request.expected_subject!r} is clearly present."
                    ),
                    observed={"text_excerpt": text[:160]},
                    expected={"subject": request.expected_subject},
                )
            )

        return issues

    def _review_image(
        self, request: ReviewRequest, settings: Mapping[str, Any]
    ) -> list[ReviewIssueItem]:
        issues: list[ReviewIssueItem] = []
        if not request.artifact_ref and not request.caption and not request.image_prompt:
            issues.append(
                self._base_issue(
                    request,
                    settings=settings,
                    issue_type="visual_mismatch",
                    severity="critical",
                    reason="No image artifact, caption, or prompt was provided for review.",
                    suggested_action="regenerate",
                    repair_instruction="Supply a managed image ref and scene context.",
                    observed={"artifact_ref": None},
                    expected={"artifact_ref": "required"},
                )
            )
            return issues

        if not request.artifact_ref:
            issues.append(
                self._base_issue(
                    request,
                    settings=settings,
                    issue_type="visual_mismatch",
                    severity="high",
                    reason="Image review is missing a managed artifact reference.",
                    suggested_action="regenerate",
                    repair_instruction="Attach the generated still as a managed artifact_ref.",
                    observed={"artifact_ref": ""},
                    expected={"artifact_ref": "non-empty relative ref"},
                )
            )

        combined = " ".join(
            part for part in (request.caption, request.image_prompt) if part
        )
        match = _PLACEHOLDER_RE.search(combined)
        if match:
            issues.append(
                self._base_issue(
                    request,
                    settings=settings,
                    issue_type="visual_mismatch",
                    severity="high",
                    reason=(
                        f"Image context contains placeholder language "
                        f"({match.group(0)!r})."
                    ),
                    suggested_action="re-prompt",
                    repair_instruction="Replace placeholders with the real scene description.",
                    observed={"placeholder": match.group(0)},
                    expected={"placeholders": False},
                )
            )

        if request.expected_subject and combined and not _contains_subject(
            combined, request.expected_subject
        ):
            issues.append(
                self._base_issue(
                    request,
                    settings=settings,
                    issue_type="visual_mismatch",
                    severity="high",
                    reason=(
                        "Image description does not match expected subject "
                        f"{request.expected_subject!r}."
                    ),
                    suggested_action="regenerate",
                    repair_instruction=(
                        f"Preserve framing; ensure subject "
                        f"{request.expected_subject!r} is clearly depicted."
                    ),
                    observed={"caption": request.caption, "image_prompt": request.image_prompt},
                    expected={"subject": request.expected_subject},
                )
            )

        if request.expected_style and combined and not _contains_subject(
            combined, request.expected_style
        ):
            issues.append(
                self._base_issue(
                    request,
                    settings=settings,
                    issue_type="visual_mismatch",
                    severity="medium",
                    reason=(
                        f"Image style cues do not match expected style "
                        f"{request.expected_style!r}."
                    ),
                    suggested_action="re-prompt",
                    repair_instruction=(
                        f"Keep subject; align style with {request.expected_style!r}."
                    ),
                    observed={"image_prompt": request.image_prompt},
                    expected={"style": request.expected_style},
                )
            )

        return issues

    def _review_video(
        self, request: ReviewRequest, settings: Mapping[str, Any]
    ) -> list[ReviewIssueItem]:
        issues: list[ReviewIssueItem] = []
        if not request.artifact_ref:
            issues.append(
                self._base_issue(
                    request,
                    settings=settings,
                    issue_type="motion_defect",
                    severity="critical",
                    reason="Video review is missing a managed artifact reference.",
                    suggested_action="regenerate",
                    repair_instruction="Attach the generated clip as a managed artifact_ref.",
                    observed={"artifact_ref": ""},
                    expected={"artifact_ref": "non-empty relative ref"},
                )
            )

        if (
            request.duration_s is not None
            and request.expected_duration_s is not None
        ):
            delta = abs(float(request.duration_s) - float(request.expected_duration_s))
            tolerance = self._duration_tolerance(settings)
            if delta > tolerance:
                issues.append(
                    self._base_issue(
                        request,
                        settings=settings,
                        issue_type="timing_drift",
                        severity="high",
                        reason=(
                            f"Video duration {request.duration_s:.2f}s differs from "
                            f"expected {request.expected_duration_s:.2f}s by "
                            f"{delta:.2f}s."
                        ),
                        suggested_action="adjust",
                        repair_instruction=(
                            "Re-time or regenerate the clip to match narration length."
                        ),
                        observed={"duration_s": request.duration_s, "delta_s": delta},
                        expected={
                            "duration_s": request.expected_duration_s,
                            "tolerance_s": tolerance,
                        },
                    )
                )

        caption = request.caption or ""
        if re.search(r"\b(?:deform|glitch|flicker|warp|artifact)\w*\b", caption, re.I):
            issues.append(
                self._base_issue(
                    request,
                    settings=settings,
                    issue_type="motion_defect",
                    severity="high",
                    reason="Video caption reports motion deformation or instability.",
                    suggested_action="regenerate",
                    repair_instruction=(
                        "Regenerate motion; preserve subject identity and framing."
                    ),
                    observed={"caption": caption[:200]},
                    expected={"motion": "stable"},
                )
            )

        if request.expected_subject and caption and not _contains_subject(
            caption, request.expected_subject
        ):
            issues.append(
                self._base_issue(
                    request,
                    settings=settings,
                    issue_type="visual_mismatch",
                    severity="medium",
                    reason=(
                        "Video caption does not mention expected subject "
                        f"{request.expected_subject!r}."
                    ),
                    suggested_action="regenerate",
                    repair_instruction=(
                        f"Keep camera move; ensure subject "
                        f"{request.expected_subject!r} remains visible."
                    ),
                    observed={"caption": caption[:200]},
                    expected={"subject": request.expected_subject},
                )
            )

        return issues

    def _review_structured(
        self, request: ReviewRequest, settings: Mapping[str, Any]
    ) -> list[ReviewIssueItem]:
        issues: list[ReviewIssueItem] = []
        data = request.structured or {}
        missing = [key for key in request.required_keys if key not in data]
        if missing:
            issues.append(
                self._base_issue(
                    request,
                    settings=settings,
                    issue_type="policy_violation",
                    severity="high",
                    reason=(
                        "Structured review subject is missing required keys: "
                        + ", ".join(missing)
                    ),
                    suggested_action="regenerate",
                    repair_instruction=(
                        "Re-emit the structured payload with all required keys present."
                    ),
                    observed={"missing_keys": missing, "present_keys": sorted(data)},
                    expected={"required_keys": list(request.required_keys)},
                )
            )

        # Empty structured object with no required_keys is still a finding —
        # structured_output capability exists to validate non-empty payloads.
        if not data and not request.required_keys:
            issues.append(
                self._base_issue(
                    request,
                    settings=settings,
                    issue_type="policy_violation",
                    severity="medium",
                    reason="Structured review subject is an empty object.",
                    suggested_action="regenerate",
                    repair_instruction="Provide a non-empty structured payload for review.",
                    observed={"keys": []},
                    expected={"non_empty": True},
                )
            )

        return issues

    def review(
        self,
        request: ReviewRequest,
        *,
        settings: Mapping[str, Any] | None = None,
    ) -> ReviewResultPayload:
        resolved = dict(settings or {})
        kind = request.subject_kind
        if kind == "text":
            findings = self._review_text(request, resolved)
        elif kind == "image":
            findings = self._review_image(request, resolved)
        elif kind == "video":
            findings = self._review_video(request, resolved)
        elif kind == "structured":
            findings = self._review_structured(request, resolved)
        else:
            # Contract already validates subject_kind; defensive fallback.
            findings = [
                self._base_issue(
                    request,
                    settings=resolved,
                    issue_type="policy_violation",
                    severity="critical",
                    reason=f"Unsupported subject_kind {kind!r}.",
                    suggested_action="escalate",
                    repair_instruction="Use image, video, text, or structured.",
                )
            ]

        return ReviewResultPayload.from_issues(
            findings,
            subject_kind=kind,
            capability=SUBJECT_CAPABILITY.get(kind, "text_review"),
        )


def create() -> SemanticReviewProvider:
    """Zero-arg factory required by the provider registry."""
    return SemanticReviewProvider()


def validate_settings(settings: dict) -> list[dict]:
    issues: list[dict] = []
    data = settings or {}
    if "min_text_words" in data and data["min_text_words"] is not None:
        try:
            value = int(data["min_text_words"])
            if value < 1:
                issues.append(
                    {
                        "field": "min_text_words",
                        "severity": "error",
                        "message": "min_text_words must be >= 1",
                    }
                )
        except (TypeError, ValueError):
            issues.append(
                {
                    "field": "min_text_words",
                    "severity": "error",
                    "message": "min_text_words must be an integer",
                }
            )
    if "confidence" in data and data["confidence"] is not None:
        try:
            conf = float(data["confidence"])
            if conf < 0.0 or conf > 1.0:
                issues.append(
                    {
                        "field": "confidence",
                        "severity": "error",
                        "message": "confidence must be between 0 and 1",
                    }
                )
        except (TypeError, ValueError):
            issues.append(
                {
                    "field": "confidence",
                    "severity": "error",
                    "message": "confidence must be a number",
                }
            )
    return issues


def health_check(settings: dict) -> dict:
    return {
        "status": "ok",
        "latency_ms": 0,
        "message": "Offline semantic reviewer ready",
    }
