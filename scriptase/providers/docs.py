"""Generate the provider reference and author guide from the live hub.

The markdown written to ``docs/providers.md`` is derived entirely from the
domain catalog and the process-wide provider hub — the same sources that drive
discovery, the catalog API, and settings. ``docs/provider-author-guide.md``
combines stable scaffold-to-ship prose with the same live tables so the guide
cannot drift from domain contracts or capability vocabularies.

Usage:
    python -m scriptase.providers.docs            # rewrite both files
    python -m scriptase.providers.docs --check    # exit 1 if stale

Also integrated into ``python -m scriptase.engine.docs`` so one drift gate covers
workflow and provider documentation.
"""

from __future__ import annotations

import importlib
import types
from pathlib import Path
from typing import Any, get_args, get_origin

from scriptase.providers.domains import (
    DOMAINS,
    SHARED_CAPABILITIES,
    DomainSpec,
)
from scriptase.providers.errors import PROVIDER_CODES, RETRYABLE
from scriptase.providers.hub import hub
from scriptase.providers.scaffold import DOMAIN_SHAPE
from scriptase.providers.settings_schema import (
    REDACTION_SENTINEL,
    SENSITIVE_KEYS_RE,
    WIDGET_TYPES,
)
from scriptase.providers.validation import KINDS

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REFERENCE_OUTPUT = REPO_ROOT / "docs" / "providers.md"
DEFAULT_AUTHOR_OUTPUT = REPO_ROOT / "docs" / "provider-author-guide.md"

_HEADER = (
    "<!-- GENERATED FILE — DO NOT EDIT BY HAND.\n"
    "     Regenerate with: python -m scriptase.engine.docs\n"
    "     (or: python -m scriptase.providers.docs)\n"
    "     Source of truth: scriptase.providers domains + hub -->\n"
)

_SHAPE_LABELS = {
    "sync_document": "sync document",
    "sync_artifact": "sync artifact",
    "async_multi_asset": "async multi-asset",
}

_SEAM_BY_DOMAIN = {
    "script": "`generate(configuration, project_id=…)` → `invoke(request, invocation)`",
    "scene_director": "`generate(segments, configuration, project_id=…)` → `invoke(…)`",
    "tts": "`synthesize(text, settings, …)` → `invoke(…)`",
    "image": "`submit` / `poll` (media-job service)",
    "video": "`submit` / `poll` (media-job service)",
    "review": "`review(request)` → `invoke(request, invocation)`",
}


def _fmt_annotation(annotation: Any) -> str:
    """Render a typing annotation as a short table cell."""
    if annotation is None or annotation is type(None):
        return "None"
    origin = get_origin(annotation)
    args = get_args(annotation)
    # Optional[T] / T | None / Union[...]
    if origin is types.UnionType or getattr(origin, "__name__", "") == "Union":
        non_none = [arg for arg in args if arg is not type(None)]
        rendered = " | ".join(_fmt_annotation(arg) for arg in non_none)
        if type(None) in args:
            return f"{rendered} | None" if rendered else "None"
        return rendered or "Any"
    if origin is list:
        return f"list[{_fmt_annotation(args[0])}]" if args else "list"
    if origin is dict:
        if len(args) == 2:
            return f"dict[{_fmt_annotation(args[0])}, {_fmt_annotation(args[1])}]"
        return "dict"
    if origin is set:
        return f"set[{_fmt_annotation(args[0])}]" if args else "set"
    if hasattr(annotation, "__name__"):
        return annotation.__name__
    return str(annotation).replace("typing.", "")


def _fmt_default(value: Any) -> str:
    if value is None:
        return "`null`"
    if value is ...:
        return "—"
    # PydanticUndefined / missing defaults.
    name = type(value).__name__
    if name in {"PydanticUndefinedType", "PydanticUndefined"} or "Undefined" in name:
        return "—"
    try:
        import json

        return f"`{json.dumps(value, ensure_ascii=False, sort_keys=True)}`"
    except TypeError:
        return f"`{value!r}`"


def _load_dotted(path: str | None) -> Any | None:
    if not path or ":" not in path:
        return None
    module_name, attr = path.rsplit(":", 1)
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return None
    return getattr(module, attr, None)


def _model_field_rows(model: Any) -> list[str]:
    """Markdown table rows for a Pydantic v2 model (or empty if unavailable)."""
    fields = getattr(model, "model_fields", None)
    if not fields:
        return []
    rows: list[str] = []
    for name, info in fields.items():
        required = getattr(info, "is_required", lambda: True)()
        default = getattr(info, "default", ...)
        default_factory = getattr(info, "default_factory", None)
        if callable(default_factory):
            default_cell = "factory"
        else:
            default_cell = _fmt_default(default)
        rows.append(
            f"| `{name}` | `{_fmt_annotation(info.annotation)}` | "
            f"{'yes' if required else 'no'} | {default_cell} |"
        )
    return rows


def _capability_cells(capabilities: dict[str, bool]) -> str:
    if not capabilities:
        return "—"
    granted = sorted(key for key, value in capabilities.items() if value)
    denied = sorted(key for key, value in capabilities.items() if not value)
    parts: list[str] = []
    if granted:
        parts.append(", ".join(f"`{key}`" for key in granted))
    if denied:
        parts.append("off: " + ", ".join(f"`{key}`" for key in denied))
    return "; ".join(parts) if parts else "—"


def _discover_catalog() -> dict[str, list[Any]]:
    """Discover every domain and return domain → ProviderInstance list."""
    hub.discover_all()
    return {domain: hub.list(domain) for domain in hub.domains()}


def _domain_table_rows() -> list[str]:
    rows: list[str] = []
    for domain_id, spec in DOMAINS.items():
        shape = _SHAPE_LABELS.get(DOMAIN_SHAPE.get(domain_id, ""), DOMAIN_SHAPE.get(domain_id, "—"))
        rows.append(
            f"| `{domain_id}` | {spec.label} | `{spec.default_provider}` | "
            f"`{spec.package}` | {shape} |"
        )
    return rows


def _provider_section(domain_id: str, providers: list[Any]) -> list[str]:
    lines = [
        f"### `{domain_id}` providers",
        "",
    ]
    if not providers:
        lines.extend(["_No providers currently registered._", ""])
        return lines
    lines.extend([
        "| Id | Label | Kind | Version | Contract | Capabilities |",
        "|---|---|---|---|---|---|",
    ])
    for provider in providers:
        manifest = provider.manifest
        lines.append(
            f"| `{manifest.id}` | {manifest.label} | `{manifest.kind}` | "
            f"`{manifest.version}` | v{manifest.contract_version} | "
            f"{_capability_cells(dict(manifest.capabilities))} |"
        )
    lines.append("")
    for provider in providers:
        manifest = provider.manifest
        lines.append(f"#### `{manifest.id}` — {manifest.label}")
        lines.append("")
        if manifest.description:
            lines.append(manifest.description)
            lines.append("")
        lines.append(f"- **Kind:** `{manifest.kind}`")
        lines.append(f"- **Version:** `{manifest.version}` (contract v{manifest.contract_version})")
        if manifest.aliases:
            aliases = ", ".join(f"`{alias}`" for alias in manifest.aliases)
            lines.append(f"- **Aliases:** {aliases}")
        if manifest.requires:
            requires = ", ".join(f"`{key}`" for key in manifest.requires)
            lines.append(f"- **Requires settings:** {requires}")
        if manifest.docs_url:
            lines.append(f"- **Docs:** {manifest.docs_url}")
        if manifest.open_url:
            lines.append(f"- **Open URL:** human-driven UI available")
        lines.append(f"- **Capabilities:** {_capability_cells(dict(manifest.capabilities))}")
        lines.append("")
    return lines


def _providers_folder_rel(spec: DomainSpec) -> str:
    """Repo-relative providers path without leaking absolute machine paths."""
    try:
        return Path(spec.providers_base).resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return "/".join(spec.package.split("."))


def _domain_contract_section(spec: DomainSpec) -> list[str]:
    lines = [
        f"### {spec.label} (`{spec.id}`)",
        "",
        f"- **Default provider:** `{spec.default_provider}`",
        f"- **Package:** `{spec.package}`",
        f"- **Providers folder:** `{_providers_folder_rel(spec)}`",
        f"- **Execution shape:** {_SHAPE_LABELS.get(DOMAIN_SHAPE.get(spec.id, ''), '—')}",
        f"- **Concrete seam:** {_SEAM_BY_DOMAIN.get(spec.id, '—')}",
        "",
        "#### Capability vocabulary",
        "",
        ", ".join(f"`{cap}`" for cap in sorted(spec.capability_vocabulary)) or "—",
        "",
    ]

    request_model = _load_dotted(spec.request_model)
    result_model = _load_dotted(spec.result_model)
    if request_model is not None:
        lines.extend([
            f"#### Request model (`{spec.request_model}`)",
            "",
            "| Field | Type | Required | Default |",
            "|---|---|---|---|",
            *_model_field_rows(request_model),
            "",
        ])
    elif spec.request_model:
        lines.extend([f"#### Request model: `{spec.request_model}`", ""])

    if result_model is not None:
        lines.extend([
            f"#### Result payload (`{spec.result_model}`)",
            "",
            "| Field | Type | Required | Default |",
            "|---|---|---|---|",
            *_model_field_rows(result_model),
            "",
        ])
    elif spec.result_model:
        lines.extend([f"#### Result payload: `{spec.result_model}`", ""])

    return lines


def generate_provider_reference() -> str:
    """Build the provider catalog reference from the live hub and domain catalog."""
    by_domain = _discover_catalog()
    total = sum(len(providers) for providers in by_domain.values())
    lines: list[str] = [
        _HEADER,
        "# Provider Reference",
        "",
        f"Live catalog: **{len(DOMAINS)} domains**, **{total} registered providers**.",
        "",
        "This document is generated from the domain catalog "
        "(`scriptase.providers.domains`) and the process-wide hub "
        "(`scriptase.providers.hub`). It is the same discovery surface "
        "served by `GET /api/providers`. Music and Captions are deliberately "
        "**not** provider domains — they remain local services without a provider "
        "dimension.",
        "",
        "Regenerate after any domain, manifest, or provider package change:",
        "",
        "```powershell",
        "python -m scriptase.engine.docs",
        "python -m scriptase.engine.docs --check",
        "```",
        "",
        "## Domains",
        "",
        "| Domain | Label | Default provider | Package | Shape |",
        "|---|---|---|---|---|",
        *_domain_table_rows(),
        "",
        "## Shared capabilities",
        "",
        "Every domain understands these capability keys. Domain-specific keys are "
        "listed under each domain below. Unknown capability keys declared on a "
        "manifest are dropped with a discovery warning.",
        "",
        ", ".join(f"`{cap}`" for cap in sorted(SHARED_CAPABILITIES)),
        "",
        "## Provider kinds",
        "",
        "| Kind | Meaning |",
        "|---|---|",
        "| `local` | In-process; no network required for the happy path |",
        "| `cloud` | External API; typically requires credentials |",
        "| `extension` | Browser extension over WebSocket; needs `register_runtime` |",
        "| `webhook` | Outbound HTTPS webhook; typically requires a URL + key |",
        "",
        f"Allowed kinds: {', '.join(f'`{kind}`' for kind in sorted(KINDS))}.",
        "",
        "## Domain contracts",
        "",
    ]
    for domain_id, spec in DOMAINS.items():
        lines.extend(_domain_contract_section(spec))

    lines.extend([
        "## Registered providers",
        "",
        "Providers are discovered by scanning each domain's `providers/` folder. "
        "There is no central registration table.",
        "",
    ])
    for domain_id in DOMAINS:
        lines.extend(_provider_section(domain_id, by_domain.get(domain_id, [])))

    lines.extend([
        "## Stable provider error codes",
        "",
        "Retryability is a property of the code, not of the provider. A provider "
        "must not mark non-retryable codes as retryable.",
        "",
        "| Code | Retryable |",
        "|---|---|",
    ])
    for code in sorted(PROVIDER_CODES):
        retry = RETRYABLE.get(code)
        if retry is None:
            cell = "per-case"
        else:
            cell = "yes" if retry else "no"
        lines.append(f"| `{code}` | {cell} |")
    lines.append("")
    return "\n".join(lines)


def generate_provider_author_guide() -> str:
    """Build the scaffold-to-ship guide with live domain tables."""
    by_domain = _discover_catalog()
    domain_ids = sorted(by_domain)
    widget_list = ", ".join(f"`{w}`" for w in sorted(WIDGET_TYPES))
    kind_list = ", ".join(f"`{k}`" for k in sorted(KINDS))

    lines: list[str] = [
        _HEADER,
        "# Provider Author Guide",
        "",
        "This is the complete path for adding a domain provider: "
        "**scaffold → manifest → settings → implementation → results/errors → "
        "artifacts → tests → health → ship**. Run commands from the repository "
        "root with the project venv (`venv/Scripts/python.exe` on this machine). "
        "Generated packages are source-controlled; a normal application restart "
        "discovers them, while development hot reload discovers saved changes when "
        "`STS_WORKFLOW_DEV_RELOAD=1`.",
        "",
        "The tables under [Live domain contracts](#live-domain-contracts) and "
        "[Current catalog](#current-catalog) come from the same domain catalog and "
        "hub that power `GET /api/providers`. Companion files:",
        "",
        "- [Provider Reference](providers.md) — full catalog generated from the hub.",
        "- [Provider template notes](provider-template/README.md) — short scaffold layout notes.",
        "- Normative machine contracts: "
        "[`contracts.md`](../_dev/loop-engineering/phases-plans/contracts.md) §19–§36.",
        "",
        "Regenerate this guide after any domain or provider change:",
        "",
        "```powershell",
        "python -m scriptase.engine.docs",
        "python -m scriptase.engine.docs --check",
        "```",
        "",
        "## Extensibility rule",
        "",
        "**A provider may not modify workflow node definitions, adapters, routes, "
        "or generic UI components.** Adding a conforming provider means creating "
        "only its package under the domain's `providers/` folder plus tests. "
        "Discovery, catalog UI, settings forms, health, and the generic domain "
        "node all consume the package through the hub. If your change requires "
        "editing `scriptase/engine/`, a shared Vue provider component, or a "
        "route dispatcher, it is not a provider plugin — stop and rework the "
        "design.",
        "",
        "## 1. Scaffold",
        "",
        "Choose a stable lowercase id matching "
        "`^[a-z][a-z0-9_]{0,31}$`. It is the folder name, the manifest `id`, and "
        f"the settings key — do not rename it after shipping. Pick one of the "
        f"{len(domain_ids)} catalog domains and a kind "
        f"({kind_list}).",
        "",
        "One command does the whole path. From the repository root:",
        "",
        "```powershell",
        "new-provider.bat tts my_provider --kind cloud",
        "```",
        "",
        "It scaffolds the package, runs the contract tests it generates, and "
        "regenerates this guide and the Provider Reference from the live hub — "
        "the three things that always belong together. Run it with no arguments "
        "to see the domains, kinds, and options. It needs no activated venv: it "
        "resolves `venv/Scripts/python.exe` itself, and stops with "
        "`start.bat -Mode setup` if that interpreter is missing.",
        "",
        "Other shapes:",
        "",
        "```powershell",
        "new-provider.bat image my_renderer --kind extension",
        "new-provider.bat scene_director my_planner --kind webhook",
        "new-provider.bat script scaffold_check          # the offline demo",
        "```",
        "",
        "This creates:",
        "",
        "- `scriptase/<domain-package>/providers/<provider_id>/manifest.py` — "
        "`ProviderManifest` with `contract_version=2`.",
        "- `…/settings_schema.py` — JSON-schema object for the generic settings UI.",
        "- `…/provider.py` — `create()` factory plus domain methods / hooks.",
        "- `…/runtime.py` — only when `--kind extension`.",
        "- `tests/test_provider_<domain>_<provider_id>.py` — generated contract tests.",
        "",
        "Nothing else changes. That is the extensibility rule above, and "
        "`tests/test_provider_extensibility.py` fails if any other shipped file "
        "starts naming a provider.",
        "",
        "The command refuses unknown domains, invalid ids, existing packages, and "
        "colliding test files. Failure is atomic — no partial provider folder is "
        "left behind. Pass `--no-tests` or `--no-docs` to skip a follow-up step, "
        "for example while scripting a batch of packages.",
        "",
        "On a non-Windows shell, or to drive it from another script, call the "
        "same CLI directly — the `.bat` only resolves the interpreter:",
        "",
        "```powershell",
        "venv/Scripts/python.exe -m scriptase.providers.scaffold tts my_provider --kind cloud",
        "```",
        "",
        "## 2. Manifest",
        "",
        "Edit `manifest.py`. Keep `id` equal to the folder name and `domain` equal "
        "to the parent domain. Required fields:",
        "",
        "| Field | Rule |",
        "|---|---|",
        "| `id` | Folder name; `^[a-z][a-z0-9_]{0,31}$` |",
        "| `label` | Browser-safe display name |",
        f"| `domain` | One of the {len(domain_ids)} catalog domains |",
        f"| `kind` | One of {kind_list} |",
        "| `version` | Semver string |",
        "| `contract_version` | `2` for the invocation/result envelope |",
        "| `capabilities` | Subset of the domain vocabulary; unknown keys warned |",
        "| `requires` | Settings **key names** that must be non-empty |",
        "| `aliases` | Optional legacy wire ids (input aliases only) |",
        "| `environment` | Setting key → env var name; **never serialized** |",
        "| `description` / `docs_url` / `open_url` | Optional browser-safe metadata |",
        "",
        "Capabilities outside the domain vocabulary are dropped with a warning at "
        "discovery. Shared keys every domain understands: "
        + ", ".join(f"`{cap}`" for cap in sorted(SHARED_CAPABILITIES))
        + ".",
        "",
        "## 3. Settings",
        "",
        "`settings_schema()` returns a JSON-schema object rendered by the generic "
        "provider settings UI. Do not hardcode fields in Vue.",
        "",
        f"Widget types (`ui.type`): {widget_list}. "
        "`text` / `number` are the defaults when `ui.type` is omitted.",
        "",
        "### Secret rules",
        "",
        f"- A field is a secret if `ui.type == \"password\"` **or** its key matches "
        f"`{SENSITIVE_KEYS_RE.pattern}`.",
        f"- Reads leave the process as the `{REDACTION_SENTINEL}` sentinel; a "
        f"write of that sentinel means \"leave the stored secret alone\".",
        "- Secrets must never appear in workflow JSON, execution records, SSE "
        "events, logs, errors, archives, notifications, or exported templates.",
        "- Environment variables are a **read-time fallback only** — they are "
        "never seeded into settings and never returned to the browser. Map them "
        "with the manifest `environment` dict.",
        "",
        "Use `validate_settings(settings)` on the provider for cross-field checks "
        "the schema cannot express. Unknown saved keys are preserved and warned; "
        "required-but-empty is an error.",
        "",
        "## 4. Implementation",
        "",
        "Every package exports `create()` — a zero-arg factory returning the "
        "provider instance. Domain bases live in "
        "`scriptase/<package>/providers/base.py`. Prefer Contract v2 `invoke()` "
        "(or the media-job service for image/video); the concrete domain "
        "seams remain for legacy adapters.",
        "",
        "| Domain | Shape | Concrete seam |",
        "|---|---|---|",
    ]
    for domain_id, spec in DOMAINS.items():
        shape = _SHAPE_LABELS.get(DOMAIN_SHAPE.get(domain_id, ""), "—")
        lines.append(
            f"| `{domain_id}` | {shape} | {_SEAM_BY_DOMAIN.get(domain_id, '—')} |"
        )
    lines.extend([
        "",
        "### Sync document example (script / scene_director)",
        "",
        "Implement `generate(...)` and/or `invoke(request, invocation) -> ProviderResult`. "
        "Build the domain request model from configuration, produce the typed result "
        "payload, write any managed files under the project output root, and return a "
        "`ProviderResult` with relative `artifact_refs` only.",
        "",
        "The committed `script/scaffold_check` demo turns idea + optional "
        "`label_prefix` into a short script, writes `story.json`, and returns a clean "
        "envelope. Its generated contract tests continue to pass without modification.",
        "",
        "### Sync artifact example (tts)",
        "",
        "Implement `synthesize(...)` / `invoke(...)` that writes audio under the "
        "managed output directory, returns `TTSResultPayload.audio_ref` as a "
        "**relative** ref (via `normalize_ref`), and never embeds absolute paths or "
        "credentials in the envelope.",
        "",
        "### Async multi-asset example (image / video)",
        "",
        "Implement `submit` + `poll` against the shared media-job service. Declare "
        "`async_job` (and `progress` / `cancel` when true). Per-unit detail belongs "
        "in `units[]`; absolute paths never leave the job status or result.",
        "",
        "### Extension providers",
        "",
        "Kind `extension` must export `register_runtime(app, sock)` (emitted as "
        "`runtime.py`). The hub binds that hook once per process after discovery. "
        "Claiming `push_callbacks` without kind `extension` is warned, not given a "
        "WebSocket route.",
        "",
        "## 5. Results and errors",
        "",
        "One envelope serves every catalog domain: `ProviderResult` "
        "(`scriptase.providers.results`). Only `payload` varies by domain. "
        "Status is `succeeded`, `partial`, or `failed`.",
        "",
        "- Raise `ProviderError(code, message, details=…)` for expected failures. "
        "Codes come from the frozen catalog (see the "
        "[Provider Reference](providers.md#stable-provider-error-codes)).",
        "- Never copy `str(exc)` from an unknown exception into a result — the "
        "boundary wraps it with a generic per-domain message.",
        "- Retryability is fixed per code. Providers do not retry generation POSTs "
        "blindly; the platform owns invocation retry.",
        "- Cancellation: providers that declare `cancel` must observe the "
        "invocation token. A cancelled remote job may still consume quota — "
        "document that for operators; the platform records node status "
        "`cancelled`, never `failed`.",
        "",
        "## 6. Artifacts",
        "",
        "Absolute filesystem paths never leave a `ProviderResult`, job status, "
        "error message, execution record, SSE frame, or API response.",
        "",
        "- Convert managed paths with `normalize_ref(absolute_path)`.",
        "- Resolve inbound refs with `resolve_ref(relative_ref)`.",
        "- `validate_egress(result)` rejects absolute paths, sensitive keys, "
        "`bytes`, non-JSON types, and oversized fields at the boundary.",
        "",
        "Write under the domain/project output roots already used by the pipeline. "
        "Use `safe_json_write` / `safe_join` for filesystem work.",
        "",
        "## 7. Tests",
        "",
        "Step 1 already ran the generated contract tests once. Re-run them as you "
        "implement, then add domain-specific cases. Reusable suites and offline "
        "fakes live in `scriptase.providers.contract_tests`.",
        "",
        "```powershell",
        "venv/Scripts/python.exe -m pytest tests/test_provider_script_scaffold_check.py -q",
        "venv/Scripts/python.exe -m pytest tests/test_provider_scaffold.py tests/test_provider_contract_kit.py -q",
        "venv/Scripts/python.exe -m scriptase.engine.docs --check",
        "```",
        "",
        "Generated tests cover discovery, catalog visibility, settings schema, "
        "health shape, and — for the working `script` skeleton — execution on the "
        "`story.generate` seam plus egress cleanliness. Those cases must keep "
        "passing without hand-edits. Deterministic suites must not require live "
        "providers (`@pytest.mark.live` stays gated by `STS_LIVE=1`).",
        "",
        "## 8. Health",
        "",
        "Implement `health_check(settings) -> HealthResult | dict` as a cheap probe. "
        "Return `{status, message, latency_ms?}` where `status` is one of "
        "`ok` / `warn` / `fail` (or the registry's accepted synonyms). Provider-authored "
        "`details` are redacted before they leave the health API. Availability "
        "(`available` / `needs_configuration` / `degraded`) is computed from settings "
        "and `requires` without network I/O; health may perform I/O and is orthogonal.",
        "",
        "One provider's import, health, execution, or shutdown failure must not hide "
        "healthy providers or take down Flask. Discovery exclusions appear in "
        "`excluded[]` with a reason code.",
        "",
        "## 9. Ship",
        "",
        "1. Keep `create()`, manifest `id`, and folder name aligned.",
        "2. Run generated + domain tests; regenerate docs "
        "(`new-provider.bat` did both for the initial scaffold — repeat with "
        "`venv/Scripts/python.exe -m scriptase.engine.docs` after later edits).",
        "3. Restart the app (or rely on dev reload).",
        "4. Confirm the provider appears in the catalog, accepts settings, reports "
        "health, and runs on the generic domain node — without editing that node.",
        "5. Commit the provider package, tests, and generated docs together.",
        "6. Removing the package folder and its test must leave no central "
        "registration entry behind.",
        "",
        "Compatibility aliases for retired wire ids belong only in the documented "
        "compatibility module / manifest `aliases` — never as new branches in "
        "generic dispatch.",
        "",
        "## Live domain contracts",
        "",
        "Field tables are loaded from each domain's request/result models at "
        "generation time.",
        "",
    ])
    for domain_id, spec in DOMAINS.items():
        lines.extend(_domain_contract_section(spec))

    lines.extend([
        "## Current catalog",
        "",
        "Snapshot of providers discovered when this guide was generated.",
        "",
        "| Domain | Providers |",
        "|---|---|",
    ])
    for domain_id in DOMAINS:
        providers = by_domain.get(domain_id, [])
        ids = ", ".join(f"`{p.id}`" for p in providers) or "—"
        lines.append(f"| `{domain_id}` | {ids} |")
    lines.extend([
        "",
        "## Troubleshooting",
        "",
        "| Symptom | Likely cause | What to do |",
        "|---|---|---|",
        "| Provider missing from catalog | Folder/id mismatch, invalid manifest, or discovery exclusion | Check app logs for `[EXCLUDED]`; fix `manifest.py` so `id` equals the folder name and `domain` matches the parent |",
        "| `needs_configuration` forever | `requires` key empty or secret never saved | Fill required settings; confirm password fields send a real value once (not only `***`) |",
        "| Health `fail` | Credentials, network, or probe bug | Run `GET /api/providers/<domain>/<id>/health` on loopback; fix `health_check` so details never echo secrets |",
        "| Settings UI blank | Missing `settings_schema.py` or empty `properties` | Ship at least one field; scaffold always includes `label_prefix` for this reason |",
        "| `PROVIDER_ARTIFACT_UNMANAGED` | Absolute path in result | Use `normalize_ref` and managed output roots only |",
        "| Contract test fails on capabilities | Declared key outside domain vocabulary | Remove the key or add it to `DomainSpec.capability_vocabulary` (platform change, not a plugin) |",
        "| Docs check fails | Manifest/domain change without regen | `python -m scriptase.engine.docs` then commit `docs/providers.md` and `docs/provider-author-guide.md` |",
        "| Wanted a new domain | Out of scope for a provider package | Add a `DomainSpec` entry and providers folder as a platform change; Music/Captions stay non-provider by design |",
        "",
        "Provider API routes are **loopback-only**. Errors use "
        '`{"error": {"code", "message", "details?"}}`.',
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate provider documentation from the domain catalog and hub."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if either committed file is stale",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_REFERENCE_OUTPUT,
        help="provider reference markdown path",
    )
    parser.add_argument(
        "--author-output",
        type=Path,
        default=DEFAULT_AUTHOR_OUTPUT,
        help="provider-author guide markdown path",
    )
    args = parser.parse_args(argv)

    reference = generate_provider_reference()
    author = generate_provider_author_guide()
    if args.check:
        current_ref = args.output.read_text(encoding="utf-8") if args.output.exists() else None
        current_author = (
            args.author_output.read_text(encoding="utf-8") if args.author_output.exists() else None
        )
        stale = [
            path
            for path, actual, expected in (
                (args.output, current_ref, reference),
                (args.author_output, current_author, author),
            )
            if actual != expected
        ]
        if stale:
            print(
                f"STALE: {', '.join(str(path) for path in stale)}. "
                "Run: python -m scriptase.providers.docs"
            )
            return 1
        print("OK: generated provider documentation matches domains and hub.")
        return 0

    for path, generated in ((args.output, reference), (args.author_output, author)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(generated, encoding="utf-8", newline="\n")
        print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
