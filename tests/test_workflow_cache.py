from __future__ import annotations

from copy import deepcopy

from scriptase.engine.cache import canonical_fingerprint, fingerprint_components
from scriptase.engine.scheduler import WorkflowScheduler


def _node(node_id, node_type, configuration):
    return {
        "id": node_id,
        "type": node_type,
        "type_version": 1,
        "name": node_id,
        "position": {"x": 0, "y": 0},
        "configuration": configuration,
        "disabled": False,
    }


def _edge(edge_id, source, target):
    return {
        "id": edge_id,
        "source_node": source,
        "source_port": "value",
        "target_node": target,
        "target_port": "value",
        "edge_type": "data",
    }


def _workflow():
    return {
        "schema_version": 1,
        "workflow_id": "wf_ABC123",
        "name": "Cache",
        "description": "",
        "nodes": [
            _node("source", "stub.input", {"port_type": "generic_json", "payload": {"version": 1}}),
            _node("viewer", "stub.output", {"port_type": "generic_json", "pinned": False, "payload": {}}),
            _node("tail", "stub.output", {"port_type": "generic_json", "pinned": False, "payload": {}}),
            _node("independent", "stub.input", {"port_type": "generic_json", "payload": {"alone": True}}),
        ],
        "edges": [_edge("e1", "source", "viewer"), _edge("e2", "viewer", "tail")],
        "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {"on_error": "stop"},
        "extensions": {},
        "created_at": "2026-08-04T12:00:00Z",
        "updated_at": "2026-08-04T12:00:00Z",
    }


def _run(workflow, tmp_path, calls, execution_id, *, force=False):
    def resolver(node):
        def execute(inputs, config, context):
            calls.append(node["id"])
            if node["type"] == "stub.input":
                return {"value": config["payload"]}
            return {"value": inputs["value"]}
        return execute

    return WorkflowScheduler(
        workflow,
        project_id="pm_ABC123",
        execution_id=execution_id,
        output_dir=str(tmp_path),
        lock_root=str(tmp_path / "locks"),
        executor_resolver=resolver,
        force=force,
    ).run()


def test_fingerprint_is_canonical_for_mapping_order():
    node = {"type": "stub.input", "type_version": 1}
    left = fingerprint_components(node, {"b": 2, "a": 1}, {"value": {"y": 2, "x": 1}}, {})
    right = fingerprint_components(node, {"a": 1, "b": 2}, {"value": {"x": 1, "y": 2}}, {})
    assert canonical_fingerprint(left) == canonical_fingerprint(right)


def test_an_adapter_schema_bump_makes_every_prior_entry_a_clean_miss():
    """Step 11.4 / acceptance A9, proved without bumping the shipped constant.

    contracts.md §45 makes `ADAPTER_CACHE_SCHEMA_VERSION` part of the
    fingerprint, so an output-shape change invalidates rather than migrates.
    Later steps bump the constant; this asserts the mechanism they rely on, and
    that the version is *only* reachable through the fingerprint — a cache entry
    written before a bump can never be read after one.
    """
    node = {"type": "tts.generate", "type_version": 1}
    before = fingerprint_components(node, {"voice": "af_heart"}, {}, {},
                                    adapter_schema_version=1)
    after = fingerprint_components(node, {"voice": "af_heart"}, {}, {},
                                   adapter_schema_version=2)
    assert before["adapter_cache_schema_version"] == 1
    assert canonical_fingerprint(before) != canonical_fingerprint(after)
    # An older entry must never be revived by bumping back down, either.
    again = fingerprint_components(node, {"voice": "af_heart"}, {}, {},
                                   adapter_schema_version=1)
    assert canonical_fingerprint(again) == canonical_fingerprint(before)


def test_unchanged_run_executes_zero_nodes_and_force_bypasses_cache(tmp_path):
    workflow = _workflow()
    first_calls = []
    _run(workflow, tmp_path, first_calls, "ex_CACHE1")
    assert set(first_calls) == {"source", "viewer", "tail", "independent"}
    assert first_calls.index("source") < first_calls.index("viewer") < first_calls.index("tail")

    second_calls = []
    second = _run(workflow, tmp_path, second_calls, "ex_CACHE2")
    assert second_calls == []
    assert all(record["cache"] == {"hit": True, "reason": "fingerprint_match"}
               for record in second.execution_record["nodes"].values())

    forced_calls = []
    forced = _run(workflow, tmp_path, forced_calls, "ex_CACHE3", force=True)
    assert set(forced_calls) == {"source", "viewer", "tail", "independent"}
    assert forced_calls.index("source") < forced_calls.index("viewer") < forced_calls.index("tail")
    assert all(record["cache"]["reason"] == "forced_regeneration"
               for record in forced.execution_record["nodes"].values())


def test_upstream_config_change_reexecutes_exactly_affected_subgraph(tmp_path):
    workflow = _workflow()
    _run(workflow, tmp_path, [], "ex_AFF001")

    changed = deepcopy(workflow)
    changed["nodes"][0]["configuration"]["payload"] = {"version": 2}
    calls = []
    result = _run(changed, tmp_path, calls, "ex_AFF002")

    assert calls == ["source", "viewer", "tail"]
    assert result.execution_record["nodes"]["source"]["cache"]["reason"] == "config_changed"
    assert result.execution_record["nodes"]["viewer"]["cache"]["reason"] == "upstream_changed"
    assert result.execution_record["nodes"]["tail"]["cache"]["reason"] == "upstream_changed"
    assert result.execution_record["nodes"]["independent"]["cache"] == {
        "hit": True, "reason": "fingerprint_match",
    }


def test_pinned_viewer_wins_until_edited(tmp_path):
    workflow = _workflow()
    workflow["nodes"][1]["configuration"] = {
        "port_type": "generic_json", "pinned": True, "payload": {"edited": 1},
    }
    first_calls = []
    first = _run(workflow, tmp_path, first_calls, "ex_PIN001")
    assert "viewer" not in first_calls
    assert first.outputs["tail"]["value"] == {"edited": 1}
    assert first.execution_record["nodes"]["viewer"]["cache"] == {
        "hit": True, "reason": "pinned_payload",
    }

    upstream_changed = deepcopy(workflow)
    upstream_changed["nodes"][0]["configuration"]["payload"] = {"version": 99}
    calls = []
    _run(upstream_changed, tmp_path, calls, "ex_PIN002")
    assert calls == ["source"]

    pin_changed = deepcopy(upstream_changed)
    pin_changed["nodes"][1]["configuration"]["payload"] = {"edited": 2}
    calls = []
    result = _run(pin_changed, tmp_path, calls, "ex_PIN003")
    assert calls == ["tail"]
    assert result.outputs["tail"]["value"] == {"edited": 2}
    assert result.execution_record["nodes"]["tail"]["cache"]["reason"] == "upstream_changed"


def test_missing_or_modified_artifact_invalidates_cache(tmp_path):
    workflow = _workflow()
    workflow["nodes"] = [_node("artifact", "trigger.manual", {})]
    workflow["edges"] = []
    artifact = tmp_path / "artifact.bin"
    calls = []

    def run(execution_id):
        def resolver(node):
            def execute(inputs, config, context):
                calls.append(node["id"])
                artifact.write_bytes(b"valid artifact")
                return {"control": {"ok": True, "artifact_refs": ["artifact.bin"]}}
            return execute
        return WorkflowScheduler(
            workflow,
            project_id="pm_ABC123",
            execution_id=execution_id,
            output_dir=str(tmp_path),
            lock_root=str(tmp_path / "locks"),
            executor_resolver=resolver,
        ).run()

    run("ex_ART001")
    run("ex_ART002")
    assert calls == ["artifact"]
    artifact.write_bytes(b"tampered")
    third = run("ex_ART003")
    assert calls == ["artifact", "artifact"]
    assert third.execution_record["nodes"]["artifact"]["cache"]["reason"] == "artifact_integrity_failed"


def test_sensitive_outputs_are_not_written_to_cache(tmp_path):
    workflow = _workflow()
    workflow["nodes"] = [_node(
        "source", "stub.input",
        {"port_type": "generic_json", "payload": {"ordinary": True}},
    )]
    workflow["edges"] = []
    secret = "cache-secret-token-123456789"

    def resolver(node):
        return lambda inputs, config, context: {"value": {"api_key": secret}}

    result = WorkflowScheduler(
        workflow,
        project_id="pm_ABC123",
        execution_id="ex_SEC002",
        output_dir=str(tmp_path),
        lock_root=str(tmp_path / "locks"),
        executor_resolver=resolver,
    ).run()
    assert result.execution_record["nodes"]["source"]["cache"] == {
        "hit": False, "reason": "sensitive_output",
    }
    cache_files = list((tmp_path / "workflows" / "cache").glob("*.json"))
    assert cache_files == []
