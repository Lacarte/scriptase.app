"""Generate workflow and provider documentation from live sources.

Workflow markdown (``docs/workflow-nodes.md``, ``docs/workflow-node-author-guide.md``)
is derived entirely from ``serialize_registry()`` (the same presentation-safe
payload the frontend consumes). Provider markdown (``docs/providers.md``,
``docs/provider-author-guide.md``) is derived from the domain catalog and the
process-wide provider hub. A pytest guard fails whenever a committed file
differs from the generator output.

Usage:
    python -m scriptase.engine.docs            # rewrite all generated guides
    python -m scriptase.engine.docs --check    # exit 1 if any guide is stale
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from scriptase.providers.docs import (
    DEFAULT_AUTHOR_OUTPUT as DEFAULT_PROVIDER_AUTHOR_OUTPUT,
    DEFAULT_REFERENCE_OUTPUT as DEFAULT_PROVIDER_OUTPUT,
    generate_provider_author_guide,
    generate_provider_reference,
)

from .registry import serialize_registry
from .templates import serialize_templates

DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "workflow-nodes.md"
DEFAULT_AUTHOR_OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "workflow-node-author-guide.md"
CONTRACTS_SOURCE = Path(__file__).resolve().parents[2] / "plans" / "contracts.md"

_CATEGORY_ORDER = [
    "input", "audio", "timing", "ai", "assets", "video", "output", "utility", "testing",
]

_HEADER = (
    "<!-- GENERATED FILE — DO NOT EDIT BY HAND.\n"
    "     Regenerate with: python -m scriptase.engine.docs\n"
    "     Source of truth: scriptase/engine/registry.py -->\n"
)
_AUTHOR_HEADER = (
    "<!-- GENERATED FILE — DO NOT EDIT BY HAND.\n"
    "     Regenerate with: python -m scriptase.engine.docs\n"
    "     Sources: plans/contracts.md and scriptase/engine/registry.py -->\n"
)


def _fmt_default(value: object) -> str:
    """Render a config default as a stable inline-code literal."""
    if value is None:
        return "—"
    return f"`{json.dumps(value, ensure_ascii=False, sort_keys=True)}`"


def _field_constraints(field: dict) -> str:
    parts: list[str] = []
    if field.get("options_source"):
        parts.append(f"options from `{field['options_source']}`")
    elif field.get("options") is not None:
        rendered = ", ".join(f"`{option}`" for option in field["options"])
        parts.append(f"one of {rendered}")
    if field.get("min") is not None or field.get("max") is not None:
        low = field.get("min", "−∞")
        high = field.get("max", "∞")
        parts.append(f"range {low}–{high}")
    if field.get("integer"):
        parts.append("integer")
    if field.get("min_length") is not None:
        parts.append(f"min length {field['min_length']}")
    if field.get("max_length") is not None:
        parts.append(f"max length {field['max_length']}")
    if field.get("pattern"):
        parts.append(f"pattern `{field['pattern']}`")
    if field.get("accept"):
        rendered = ", ".join(f"`{ext}`" for ext in field["accept"])
        parts.append(f"file types {rendered}")
    if field.get("display_options"):
        conditions = []
        for mode in ("show", "hide"):
            for name, values in (field["display_options"].get(mode) or {}).items():
                rendered = " or ".join(f"`{json.dumps(v)}`" for v in values)
                verb = "shown when" if mode == "show" else "hidden when"
                conditions.append(f"{verb} `{name}` is {rendered}")
        parts.extend(conditions)
    return "; ".join(parts) if parts else "—"


def _port_rows(ports: list[dict], *, is_input: bool) -> list[str]:
    rows = []
    for port in ports:
        flags = []
        if is_input:
            flags.append("required" if port.get("required") else "optional")
            if port.get("multiple"):
                flags.append("multiple connections")
        if port.get("conditional"):
            flags.append("conditional branch")
        rows.append(f"| `{port['id']}` | `{port['type']}` | {', '.join(flags) if flags else '—'} |")
    return rows


def _capability_summary(capabilities: dict) -> str:
    labels = {
        "retry": "retry",
        "cancel": "cancel",
        "error_output": "error output",
        "skip_optional": "skip-optional",
        "cacheable": "cacheable",
    }
    granted = [label for key, label in labels.items() if capabilities.get(key)]
    denied = [label for key, label in labels.items() if key in capabilities and not capabilities.get(key)]
    parts = []
    if granted:
        parts.append("supports " + ", ".join(granted))
    if denied:
        parts.append("no " + ", ".join(denied))
    return "; ".join(parts) if parts else "—"


def generate_node_reference() -> str:
    registry = serialize_registry()
    node_types = registry["node_types"]
    categories = registry["categories"]

    lines: list[str] = [_HEADER]
    lines.append("# Workflow Node Reference")
    lines.append("")
    lines.append(
        f"Registry version **{registry['registry_version']}** — "
        f"{len(node_types)} node types across {len(categories)} categories."
    )
    lines.append("")
    lines.append(
        "Connections require the source and target port to have the **same** type; "
        "there are no implicit conversions. `control` ports carry execution order "
        "only and never data. Dynamic ports (`stub.input`, `stub.output`, "
        "`workflow.output`) take the type chosen in the node's `port_type` setting."
    )
    lines.append("")

    # Port type vocabulary.
    lines.append("## Port types")
    lines.append("")
    lines.append("| Type |")
    lines.append("|---|")
    for port_type in registry["port_types"]:
        lines.append(f"| `{port_type}` |")
    lines.append("")

    # Category index.
    lines.append("## Categories")
    lines.append("")
    lines.append("| Category | Label | Color |")
    lines.append("|---|---|---|")
    for key in _CATEGORY_ORDER:
        info = categories[key]
        lines.append(f"| `{key}` | {info['label']} | `{info['color']}` |")
    lines.append("")

    # Nodes grouped by category, in registry order inside each category.
    for category_key in _CATEGORY_ORDER:
        members = [
            (type_key, definition)
            for type_key, definition in node_types.items()
            if definition["category"] == category_key
        ]
        if not members:
            continue
        lines.append(f"## {categories[category_key]['label']} nodes")
        lines.append("")
        for type_key, definition in members:
            lines.append(f"### {definition['display_name']} (`{type_key}`)")
            lines.append("")
            lines.append(f"{definition['description']}")
            lines.append("")
            lines.append(
                f"- **Type version:** {definition['type_version']}"
            )
            lines.append(f"- **Capabilities:** {_capability_summary(definition.get('capabilities', {}))}")
            lines.append("")
            inputs = definition.get("inputs", [])
            if inputs:
                lines.append("**Inputs**")
                lines.append("")
                lines.append("| Port | Type | Notes |")
                lines.append("|---|---|---|")
                lines.extend(_port_rows(inputs, is_input=True))
                lines.append("")
            else:
                lines.append("**Inputs:** none")
                lines.append("")
            outputs = definition.get("outputs", [])
            if outputs:
                lines.append("**Outputs**")
                lines.append("")
                lines.append("| Port | Type | Notes |")
                lines.append("|---|---|---|")
                lines.extend(_port_rows(outputs, is_input=False))
                lines.append("")
            else:
                lines.append("**Outputs:** none")
                lines.append("")
            fields = definition.get("config_schema", [])
            if fields:
                lines.append("**Configuration**")
                lines.append("")
                lines.append("| Field | Label | Widget | Default | Required | Constraints |")
                lines.append("|---|---|---|---|---|---|")
                for field in fields:
                    lines.append(
                        f"| `{field['name']}` | {field['label']} | `{field['type']}` "
                        f"| {_fmt_default(field.get('default'))} "
                        f"| {'yes' if field.get('required') else 'no'} "
                        f"| {_field_constraints(field)} |"
                    )
                lines.append("")
            else:
                lines.append("**Configuration:** none")
                lines.append("")

    # Built-in templates, generated from the same validated source.
    lines.append("## Built-in templates")
    lines.append("")
    lines.append("| Template | Name | Nodes | Description |")
    lines.append("|---|---|---|---|")
    for entry in serialize_templates():
        workflow = entry["workflow"]
        node_list = ", ".join(f"`{node['type']}`" for node in workflow["nodes"])
        lines.append(
            f"| `{entry['template_id']}` | {workflow['name']} "
            f"| {node_list} | {workflow.get('description', '')} |"
        )
    lines.append("")
    return "\n".join(lines)


def _contract_connection_rules(path: Path = CONTRACTS_SOURCE) -> str:
    """Read the normative port-compatibility prose from contracts.md.

    The type inventory is deliberately omitted because the registry is the
    executable source of truth for that list. Keeping the behavioral prose in
    the frozen contract means this guide cannot silently paraphrase it into a
    different connection model.
    """
    source = path.read_text(encoding="utf-8")
    match = re.search(
        r"(?ms)^###\s+\d+(?:\.\d+)*\s+Port types & compatibility matrix\s*$"
        r"(?P<section>.*?)(?=^###\s+|\Z)",
        source,
    )
    if match is None:
        raise RuntimeError(f"Cannot find the port compatibility section in {path}")
    section = match.group("section")
    paragraphs = [part.strip() for part in section.strip().split("\n\n")]
    return "\n\n".join(part for part in paragraphs if not part.startswith("Types (v1):"))


def _port_signature(ports: list[dict], *, inputs: bool) -> str:
    if not ports:
        return "—"
    rendered = []
    for port in ports:
        suffix = ""
        if inputs and not port.get("required"):
            suffix += "?"
        if inputs and port.get("multiple"):
            suffix += "*"
        rendered.append(f"`{port['id']}:{port['type']}{suffix}`")
    return ", ".join(rendered)


def generate_node_author_guide(*, contracts_path: Path = CONTRACTS_SOURCE) -> str:
    """Build the scaffold-to-ship guide from contracts plus live registry."""
    registry = serialize_registry()
    node_types = registry["node_types"]
    lines = [
        _AUTHOR_HEADER,
        "# Workflow Node Author Guide",
        "",
        "This is the complete path for adding a backend workflow node: **scaffold → schema → adapter → test → ship**. "
        "Run commands from the repository root with Python 3.10 or newer. The generated files are source-controlled; "
        "a normal application restart discovers them, while development hot reload discovers saved changes when "
        "`STS_WORKFLOW_DEV_RELOAD=1`.",
        "",
        "The tables under [Registry-generated contracts](#registry-generated-contracts) come from the same registry "
        "served to the palette. The connection prose comes verbatim from the normative "
        "[`contracts.md`](../plans/contracts.md) section 1.1. Regenerate this guide after "
        "any registry or contract change:",
        "",
        "```powershell",
        "python -m scriptase.engine.docs",
        "python -m scriptase.engine.docs --check",
        "```",
        "",
        "## 1. Scaffold",
        "",
        "Choose a stable lowercase dotted key. It is persisted in workflows, so do not rename it after shipping. "
        "Declare data ports on the command line; the scaffolder adds optional `trigger:control` and "
        "`control:control` ports itself. `control` is reserved and cannot be passed to `--input` or `--output`.",
        "",
        "The step 8.1 demo is reproducible with:",
        "",
        "```powershell",
        "python -m scriptase.engine.scaffold scaffold_check.echo `",
        "  --input source:generic_json `",
        "  --output result:generic_json `",
        "  --category testing `",
        "  --display-name \"Scaffold Check Echo\" `",
        "  --description \"Echo a JSON value for node-author verification.\"",
        "```",
        "",
        "This creates exactly three files:",
        "",
        "- `scriptase/engine/node_definitions/scaffold_check.echo.json` — registry metadata and configuration schema.",
        "- `scriptase/engine/adapters/generated/scaffold_check_echo.py` — executable adapter.",
        "- `tests/test_workflow_node_scaffold_check_echo.py` — passing registry and execution smoke tests.",
        "",
        "The command refuses an existing registry key, an existing target file, malformed IDs, duplicate/reserved "
        "port IDs, and types outside the generated table below. Use `python -m scriptase.engine.scaffold --help` "
        "for all options.",
        "",
        "## 2. Define the schema",
        "",
        "Edit the generated JSON definition. Keep port IDs stable and make each input's `required` and `multiple` "
        "flags intentional. Outputs may fan out; `multiple: true` on an input permits more than one incoming edge. "
        "Do not use `dynamic` for authored nodes—it is reserved for the built-in stubs and Workflow Output.",
        "",
        "Configuration fields render directly in the inspector. Supported widgets are `string`, `textarea`, "
        "`number`, `boolean`, `options`, `json`, and `media_asset`. Every field needs `name`, `label`, `type`, and "
        "`default`. Useful optional constraints are `required`, `min`, `max`, `integer`, `min_length`, `max_length`, "
        "`pattern`, `options`, `options_source`, `accept`, and `display_options`. Use only an existing allowlisted "
        "`options_source`; registry tests enforce this.",
        "",
        "Capabilities describe scheduler behavior: set `retry` only for safe repeatable attempts, `cancel` only when "
        "the adapter cooperatively observes cancellation, and `cacheable: false` when executing the node is itself "
        "the intended side effect. The registry supplies error/skip outputs for ordinary control-producing nodes.",
        "",
        "When a released schema changes, increment `type_version` and add every sequential migration as a "
        "`module:function` entry under `migrations` (for example, key `\"1\"` upgrades configuration from 1 to 2). "
        "A migration accepts and returns a configuration object and must not mutate files or external state.",
        "",
        "## 3. Implement the adapter",
        "",
        "Adapters have one boundary: `execute(inputs, config, context) -> outputs`. `inputs` and `config` are resolved "
        "mappings. `context` is an `AdapterContext` (mapping-compatible in tests) with project/execution/node IDs, "
        "progress and stop callbacks, existing-project authorization, and optional staged-artifact support.",
        "",
        "Use helpers from `scriptase.engine.adapters.common`: `outputs(...)` adds the control token, `AdapterError` "
        "reports a stable code and safe message, `project_id(...)` resolves a strict project ID, `inherited_config(...)` "
        "applies explicit-over-inherited settings, and `with_artifacts(...)` emits managed relative artifact refs. "
        "Call importable Python services directly—never call this application's Flask routes over HTTP. Use "
        "`safe_json_read`, `safe_json_write`, `safe_join`, and configured directory constants for filesystem work.",
        "",
        "The committed demo turns the scaffold placeholder into a real deterministic echo: it returns `source` when "
        "connected and otherwise the configured `value`. Its generated smoke test therefore continues to pass "
        "without modification.",
        "",
        "Adapter checklist:",
        "",
        "- Return only declared output port IDs; omit an inactive conditional branch instead of returning `null`.",
        "- Raise `AdapterError(code, message, details=...)` for expected failures; never include secrets in details.",
        "- Keep output payloads JSON-serializable. Put large/file-backed results under managed output roots and include `artifact_refs`.",
        "- Stage newly created artifacts through `context.stage_artifact` when atomic publication matters.",
        "- Report meaningful progress through `context.progress` and check `context.stop_requested` only if `cancel` is advertised.",
        "- Keep provider IDs canonical and obtain providers through their registries rather than importing synthetic modules.",
        "",
        "## 4. Test",
        "",
        "Run the generated smoke test first, then add behavior tests beside it for defaults, every output branch, "
        "validation failures, structured errors, cancellation/retry claims, and artifact containment as applicable.",
        "",
        "```powershell",
        "python -m pytest tests/test_workflow_node_scaffold_check_echo.py -q",
        "python -m pytest tests/test_workflow_scaffold.py tests/test_workflow_registry.py tests/test_workflow_docs.py -q",
        "python -m scriptase.engine.docs --check",
        "```",
        "",
        "For a provider or filesystem node, also test with deterministic fixtures from `scriptase/engine/fixtures/`; "
        "normal tests must not require live providers. Before shipping, run the complete relevant backend suite and "
        "the frontend workflow tests if registry presentation changed.",
        "",
        "## 5. Ship",
        "",
        "Regenerate and commit both documentation files. Restart the app (or confirm a successful dev-reload event), "
        "verify the node appears in the intended palette category, configure it, connect only exact-type ports, "
        "validate the graph, and execute it. Review the execution record for output summaries, redaction, cache "
        "behavior, and managed artifact references. Commit the definition, adapter, tests, generated docs, and any "
        "migration module together.",
        "",
        "## Registry-generated contracts",
        "",
        f"Registry version **{registry['registry_version']}**.",
        "",
        "### Allowed port types",
        "",
        "| Port type | CLI data port? |",
        "|---|---|",
    ]
    for port_type in registry["port_types"]:
        lines.append(f"| `{port_type}` | {'no — reserved for execution order' if port_type == 'control' else 'yes'} |")
    lines.extend([
        "",
        "### Frozen connection rules",
        "",
        _contract_connection_rules(contracts_path),
        "",
        "### Current node port matrix",
        "",
        "`?` marks an optional input and `*` marks a multiple-connection input.",
        "",
        "| Node type | Inputs | Outputs |",
        "|---|---|---|",
    ])
    for type_key, definition in node_types.items():
        lines.append(
            f"| `{type_key}` | {_port_signature(definition.get('inputs', []), inputs=True)} "
            f"| {_port_signature(definition.get('outputs', []), inputs=False)} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate workflow and provider documentation from live sources."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if any committed generated file is stale",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="node reference markdown path")
    parser.add_argument(
        "--author-output",
        type=Path,
        default=DEFAULT_AUTHOR_OUTPUT,
        help="node-author guide output markdown path",
    )
    parser.add_argument(
        "--provider-output",
        type=Path,
        default=DEFAULT_PROVIDER_OUTPUT,
        help="provider reference markdown path",
    )
    parser.add_argument(
        "--provider-author-output",
        type=Path,
        default=DEFAULT_PROVIDER_AUTHOR_OUTPUT,
        help="provider-author guide markdown path",
    )
    args = parser.parse_args(argv)

    targets = (
        (args.output, generate_node_reference()),
        (args.author_output, generate_node_author_guide()),
        (args.provider_output, generate_provider_reference()),
        (args.provider_author_output, generate_provider_author_guide()),
    )
    if args.check:
        stale = [
            path
            for path, expected in targets
            if (path.read_text(encoding="utf-8") if path.exists() else None) != expected
        ]
        if stale:
            print(f"STALE: {', '.join(str(path) for path in stale)}. Run: python -m scriptase.engine.docs")
            return 1
        print("OK: generated workflow and provider documentation matches live sources.")
        return 0
    for path, generated in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(generated, encoding="utf-8", newline="\n")
        print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
