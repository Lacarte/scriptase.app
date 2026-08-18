from __future__ import annotations

import os
import threading
import time

import pytest

from scriptase.engine.scheduler import (
    ArtifactPromoter,
    ProjectLock,
    ProjectLockedError,
    WorkflowScheduler,
    calculate_scope,
    dependency_maps,
    deterministic_order,
)
from scriptase.engine.registry import get_node_type


def _node(node_id, node_type="trigger.manual", *, disabled=False, port_type=None, config=None):
    if config is None:
        config = {} if port_type is None else {"port_type": port_type, "payload": {}}
    defn = get_node_type(node_type)
    ver = defn["type_version"] if defn else 1
    return {
        "id": node_id, "type": node_type, "type_version": ver, "name": node_id,
        "position": {"x": 0, "y": 0}, "configuration": config, "disabled": disabled,
    }


def _edge(edge_id, source, source_port, target, target_port, edge_type="control"):
    return {
        "id": edge_id, "source_node": source, "source_port": source_port,
        "target_node": target, "target_port": target_port, "edge_type": edge_type,
    }


def _workflow(nodes, edges):
    return {
        "schema_version": 1, "workflow_id": "wf_ABC123", "name": "Schedule",
        "description": "", "nodes": nodes, "edges": edges, "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1}, "settings": {"on_error": "stop"},
        "created_at": "2026-08-04T12:00:00Z", "updated_at": "2026-08-04T12:00:00Z",
    }


def _resolver(calls, behavior=None):
    behavior = behavior or {}
    def resolve(node):
        def execute(inputs, config, context):
            calls.append((node["id"], inputs))
            defaults = {
                port["id"]: ({"ok": True} if port["id"] == "control" else {})
                for port in get_node_type(node["type"])["outputs"]
            }
            return behavior.get(node["id"], defaults)
        return execute
    return resolve


def test_order_is_deterministic_by_saved_order_then_id(tmp_path):
    workflow = _workflow(
        [_node("root"), _node("later", "project.setup"),
         _node("earlier", "project.setup"), _node("join", "project.setup")],
        [_edge("e1", "root", "control", "later", "trigger"),
         _edge("e2", "root", "control", "earlier", "trigger"),
         _edge("e3", "later", "control", "join", "trigger")],
    )
    assert deterministic_order(workflow) == ["root", "later", "earlier", "join"]
    calls = []
    result = WorkflowScheduler(workflow, project_id="pm_ABC123", lock_root=str(tmp_path / "locks"),
                               output_dir=str(tmp_path), executor_resolver=_resolver(calls)).run()
    call_ids = [node_id for node_id, _ in calls]
    assert result.order == ["root", "later", "earlier", "join"]
    assert call_ids[0] == "root"
    assert set(call_ids[1:3]) == {"later", "earlier"}
    assert call_ids[-1] == "join"
    dependencies, reverse = dependency_maps(workflow)
    assert dependencies["join"] == {"later"}
    assert reverse["root"] == {"later", "earlier"}


def test_multi_input_and_diamond_join_wait_for_every_predecessor(tmp_path):
    nodes = [_node("source"), _node("left", "script.input", config={"text": "hello"}),
             _node("right", "project.setup"), _node("join", "tts.generate")]
    edges = [
        _edge("e1", "source", "control", "left", "trigger"),
        _edge("e2", "source", "control", "right", "trigger"),
        _edge("e3", "left", "script", "join", "script", "data"),
        _edge("e4", "right", "settings", "join", "settings", "data"),
    ]
    workflow = _workflow(nodes, edges)
    calls = []
    behavior = {
        "source": {"control": {"ok": True}},
        "left": {"control": {"ok": True}, "script": "script-value"},
        "right": {"control": {"ok": True}, "settings": {"tone": "test"}},
        "join": {"control": {"ok": True}, "audio": {}, "metadata": {}},
    }
    # Test executors deliberately expose extra ports; the scheduler consumes
    # only those named by graph edges.
    result = WorkflowScheduler(workflow, project_id="pm_ABC123", lock_root=str(tmp_path / "locks"),
                               output_dir=str(tmp_path), executor_resolver=_resolver(calls, behavior)).run()
    assert result.status == "succeeded"
    assert calls[-1] == ("join", {"script": "script-value", "settings": {"tone": "test"}})
    assert result.order == ["source", "left", "right", "join"]


def test_diamond_branches_overlap_and_keep_deterministic_node_events(tmp_path):
    nodes = [
        _node("source"),
        _node("left", "script.input", config={"text": "hello"}),
        _node("right", "project.setup"),
        _node("join", "tts.generate"),
    ]
    edges = [
        _edge("e1", "source", "control", "left", "trigger"),
        _edge("e2", "source", "control", "right", "trigger"),
        _edge("e3", "left", "script", "join", "script", "data"),
        _edge("e4", "right", "settings", "join", "settings", "data"),
    ]
    workflow = _workflow(nodes, edges)
    branch_barrier = threading.Barrier(2)
    intervals = {}
    events = []

    def resolver(node):
        def execute(inputs, config, context):
            started = time.perf_counter()
            if node["id"] in {"left", "right"}:
                branch_barrier.wait(timeout=2)
                time.sleep(0.03)
            intervals[node["id"]] = (started, time.perf_counter())
            if node["id"] == "source":
                return {"control": {"ok": True}}
            if node["id"] == "left":
                return {"control": {"ok": True}, "script": "hello"}
            if node["id"] == "right":
                return {"control": {"ok": True}, "settings": {}}
            return {"control": {"ok": True}, "audio": {}, "metadata": {}}
        return execute

    result = WorkflowScheduler(
        workflow,
        project_id="pm_ABC123",
        lock_root=str(tmp_path / "locks"),
        output_dir=str(tmp_path),
        executor_resolver=resolver,
        on_event=events.append,
        max_workers=2,
    ).run()

    assert result.status == "succeeded"
    assert result.order == ["source", "left", "right", "join"]
    assert intervals["left"][0] < intervals["right"][1]
    assert intervals["right"][0] < intervals["left"][1]
    for node_id in result.order:
        assert [
            event["status"] for event in events
            if event.get("type") == "node_status" and event.get("node_id") == node_id
        ] == ["running", "succeeded"]


def test_parallel_unsafe_nodes_execute_exclusively(tmp_path):
    workflow = _workflow(
        [
            _node("source", "script.input", config={"text": "hello"}),
            _node("left", "tts.generate"),
            _node("right", "tts.generate"),
        ],
        [
            _edge("e1", "source", "script", "left", "script", "data"),
            _edge("e2", "source", "script", "right", "script", "data"),
        ],
    )
    state_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def resolver(node):
        def execute(inputs, config, context):
            nonlocal active, maximum_active
            if node["id"] == "source":
                return {"control": {"ok": True}, "script": "hello"}
            with state_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.03)
            with state_lock:
                active -= 1
            return {"control": {"ok": True}, "audio": {}, "metadata": {}}
        return execute

    result = WorkflowScheduler(
        workflow,
        project_id="pm_ABC123",
        lock_root=str(tmp_path / "locks"),
        output_dir=str(tmp_path),
        executor_resolver=resolver,
        max_workers=4,
    ).run()

    assert result.status == "succeeded"
    assert maximum_active == 1


def test_partial_run_scopes_on_branch_and_diamond_graph():
    #       root
    #      /    \
    #   left   right
    #      \    /
    #       join -> tail
    workflow = _workflow(
        [_node("root"), _node("left"), _node("right"), _node("join"), _node("tail")],
        [
            _edge("e1", "root", "control", "left", "trigger"),
            _edge("e2", "root", "control", "right", "trigger"),
            _edge("e3", "left", "control", "join", "trigger"),
            _edge("e4", "right", "control", "join", "trigger"),
            _edge("e5", "join", "control", "tail", "trigger"),
        ],
    )
    assert calculate_scope(workflow, "selected", ["left", "right"]) == ["root", "left", "right"]
    assert calculate_scope(workflow, "from_node", ["left"]) == ["left", "join", "tail"]
    assert calculate_scope(workflow, "retry_failed", ["join"]) == ["join"]
    assert calculate_scope(workflow, "retry_failed_desc", ["left"]) == ["left", "join", "tail"]


@pytest.mark.parametrize(
    ("mode", "targets", "message"),
    [
        ("selected", [], "at least one"),
        ("selected", ["root", "root"], "duplicates"),
        ("from_node", ["missing"], "Unknown target"),
        ("retry_failed", ["root", "left"], "exactly one"),
        ("not_a_mode", [], "Unsupported"),
    ],
)
def test_partial_run_scope_rejects_invalid_requests(mode, targets, message):
    workflow = _workflow([_node("root"), _node("left")], [])
    with pytest.raises(ValueError, match=message):
        calculate_scope(workflow, mode, targets)


def test_disabled_node_and_its_dependent_are_skipped_but_other_branch_runs(tmp_path):
    workflow = _workflow(
        [_node("root"), _node("off", "project.setup", disabled=True),
         _node("blocked", "project.setup"), _node("independent")],
        [_edge("e1", "root", "control", "off", "trigger"),
         _edge("e2", "off", "control", "blocked", "trigger")],
    )
    calls = []
    result = WorkflowScheduler(workflow, project_id="pm_ABC123", lock_root=str(tmp_path / "locks"),
                               output_dir=str(tmp_path), executor_resolver=_resolver(calls)).run()
    assert result.node_statuses == {
        "root": "succeeded", "off": "skipped", "blocked": "skipped", "independent": "succeeded",
    }
    assert [node_id for node_id, _ in calls] == ["root", "independent"]


def test_v1_stop_policy_skips_every_node_after_failure(tmp_path):
    workflow = _workflow([_node("bad"), _node("otherwise")], [])
    calls = []

    def resolver(node):
        def execute(inputs, config, context):
            calls.append(node["id"])
            if node["id"] == "bad":
                raise RuntimeError("boom")
            return {"control": {"ok": True}}
        return execute

    result = WorkflowScheduler(workflow, project_id="pm_ABC123", lock_root=str(tmp_path / "locks"),
                               output_dir=str(tmp_path), executor_resolver=resolver).run()
    assert result.status == "failed"
    assert result.node_statuses == {"bad": "failed", "otherwise": "skipped"}
    assert calls == ["bad"]


def _retry_workflow(policy, *, with_error_branch=False, with_success_branch=False):
    nodes = [
        _node("source", "script.input", config={"text": "hello"}),
        {**_node("work", "tts.generate"), "on_error": policy},
    ]
    edges = [_edge("e_script", "source", "script", "work", "script", "data")]
    if with_error_branch:
        nodes.append(_node("recovery", "project.setup"))
        edges.append(_edge("e_error", "work", "error", "recovery", "trigger"))
    if with_success_branch:
        nodes.append(_node("success", "project.setup"))
        edges.append(_edge("e_success", "work", "control", "success", "trigger"))
    return _workflow(nodes, edges)


def test_retry_policy_uses_bounded_attempts_and_exponential_backoff(tmp_path):
    workflow = _retry_workflow({
        "policy": "retry", "max_attempts": 3, "delay_ms": 100, "backoff_multiplier": 2,
    })
    calls, sleeps, events = [], [], []

    def resolver(node):
        def execute(inputs, config, context):
            calls.append(node["id"])
            if node["id"] == "work" and calls.count("work") < 3:
                raise RuntimeError("temporary provider failure")
            if node["id"] == "source":
                return {"control": {"ok": True}, "script": "hello"}
            return {"control": {"ok": True}, "audio": {}, "metadata": {}}
        return execute

    result = WorkflowScheduler(
        workflow, project_id="pm_ABC123", lock_root=str(tmp_path / "locks"),
        output_dir=str(tmp_path), executor_resolver=resolver, sleeper=sleeps.append,
        on_event=events.append,
    ).run()
    assert result.status == "succeeded"
    assert result.execution_record["nodes"]["work"]["attempts"] == 3
    assert len(result.execution_record["nodes"]["work"]["attempt_errors"]) == 2
    assert sum(sleeps) == pytest.approx(0.3)
    assert [event["delay_ms"] for event in events if event["type"] == "node_retry"] == [100, 200]


def test_retry_policy_stops_after_bound_and_emits_structured_failure(tmp_path):
    workflow = _retry_workflow({
        "policy": "retry", "max_attempts": 2, "delay_ms": 0, "backoff_multiplier": 1,
    })

    def resolver(node):
        def execute(inputs, config, context):
            if node["id"] == "work":
                raise RuntimeError("provider exploded")
            return {"control": {"ok": True}, "script": "hello"}
        return execute

    result = WorkflowScheduler(
        workflow, project_id="pm_ABC123", lock_root=str(tmp_path / "locks"),
        output_dir=str(tmp_path), executor_resolver=resolver,
    ).run()
    error = result.errors["work"]
    assert result.status == "failed"
    assert error.keys() == {
        "node_id", "node_name", "code", "message", "details", "attempt",
        "timestamp", "recovery_suggestion",
    }
    assert error["node_id"] == "work"
    assert error["attempt"] == 2
    assert error["code"] == "NODE_EXECUTION_FAILED"
    assert error["recovery_suggestion"]


def test_continue_error_activates_only_explicit_error_control_branch(tmp_path):
    workflow = _retry_workflow(
        {"policy": "continue_error"}, with_error_branch=True, with_success_branch=True,
    )
    calls = []

    def resolver(node):
        def execute(inputs, config, context):
            calls.append(node["id"])
            if node["id"] == "source":
                return {"control": {"ok": True}, "script": "hello"}
            if node["id"] == "work":
                raise RuntimeError("route me")
            return {"control": {"ok": True}, "settings": {}}
        return execute

    result = WorkflowScheduler(
        workflow, project_id="pm_ABC123", lock_root=str(tmp_path / "locks"),
        output_dir=str(tmp_path), executor_resolver=resolver,
    ).run()
    assert result.status == "partial"
    assert result.node_statuses == {
        "source": "succeeded", "work": "failed", "recovery": "succeeded", "success": "skipped",
    }
    assert calls == ["source", "work", "recovery"]
    assert result.outputs["work"] == {"error": {"ok": False}}


def test_skip_optional_records_failure_but_allows_independent_work(tmp_path):
    workflow = _retry_workflow({"policy": "skip_optional"}, with_success_branch=True)
    workflow["nodes"].append(_node("independent"))
    calls = []

    def resolver(node):
        def execute(inputs, config, context):
            calls.append(node["id"])
            if node["id"] == "source":
                return {"control": {"ok": True}, "script": "hello"}
            if node["id"] == "work":
                raise RuntimeError("optional failure")
            definition = get_node_type(node["type"])
            return {port["id"]: {} for port in definition["outputs"] if port["id"] != "error"}
        return execute

    result = WorkflowScheduler(
        workflow, project_id="pm_ABC123", lock_root=str(tmp_path / "locks"),
        output_dir=str(tmp_path), executor_resolver=resolver,
    ).run()
    assert result.status == "partial"
    assert result.node_statuses["work"] == "skipped"
    assert result.node_statuses["success"] == "skipped"
    assert result.node_statuses["independent"] == "succeeded"
    assert "independent" in calls


def test_project_lock_contention_is_non_blocking_and_releases(tmp_path):
    root = str(tmp_path / "locks")
    with ProjectLock("pm_ABC123", lock_root=root, execution_id="ex_FIRST1"):
        with pytest.raises(ProjectLockedError) as error:
            ProjectLock("pm_ABC123", lock_root=root, execution_id="ex_SECOND").acquire()
        assert error.value.code == "PROJECT_LOCKED"
        # Different projects never contend.
        with ProjectLock("pm_DEF456", lock_root=root):
            pass
    with ProjectLock("pm_ABC123", lock_root=root):
        pass


def test_concurrent_project_lock_has_exactly_one_winner(tmp_path):
    root = str(tmp_path / "locks")
    barrier = threading.Barrier(2)
    outcomes = []

    def attempt():
        barrier.wait()
        try:
            with ProjectLock("pm_ABC123", lock_root=root):
                outcomes.append("acquired")
                barrier.wait()
        except ProjectLockedError:
            outcomes.append("locked")
            barrier.wait()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["acquired", "locked"]


def test_artifact_is_only_visible_after_atomic_promotion(tmp_path):
    promoter = ArtifactPromoter(output_dir=str(tmp_path), execution_id="ex_TEST12")
    destination = tmp_path / "projects" / "pm_ABC123" / "result.txt"
    staged = promoter.stage_path(str(destination))
    with open(staged, "w", encoding="utf-8") as handle:
        handle.write("complete")
    assert not destination.exists()
    promoter.promote()
    assert destination.read_text(encoding="utf-8") == "complete"
    promoter.cleanup()
    assert not os.path.exists(promoter.staging_dir)


def test_scheduler_promotes_staged_artifact_only_after_adapter_success(tmp_path):
    workflow = _workflow([_node("root")], [])
    destination = tmp_path / "projects" / "pm_ABC123" / "result.txt"

    def resolver(node):
        def execute(inputs, config, context):
            staged = context.stage_artifact(str(destination))
            with open(staged, "w", encoding="utf-8") as handle:
                handle.write("published")
            assert not destination.exists()
            return {"control": {"ok": True}}
        return execute

    result = WorkflowScheduler(workflow, project_id="pm_ABC123", lock_root=str(tmp_path / "locks"),
                               output_dir=str(tmp_path), executor_resolver=resolver).run()
    assert result.status == "succeeded"
    assert destination.read_text(encoding="utf-8") == "published"


# -- step 11.4: the error boundary at the scheduler edge ---------------------


def _failing_scheduler(tmp_path, exception, *, on_error=None, **kwargs):
    workflow = _retry_workflow(on_error or {"policy": "stop"})

    def resolver(node):
        def execute(inputs, config, context):
            if node["id"] == "work":
                raise exception
            return {"control": {"ok": True}, "script": "hello"}
        return execute

    return WorkflowScheduler(
        workflow, project_id="pm_ABC123", lock_root=str(tmp_path / "locks"),
        output_dir=str(tmp_path), executor_resolver=resolver, **kwargs,
    ).run()


def test_an_unhandled_adapter_exception_never_persists_its_text(tmp_path):
    """contracts.md §34.4 / §36 L1: `_failure_payload` no longer copies str(exc)."""
    result = _failing_scheduler(
        tmp_path, RuntimeError("key sk-abc123def456 at C:\\secret\\file.txt")
    )
    error = result.errors["work"]
    record = result.execution_record["nodes"]["work"]
    assert error["code"] == "NODE_EXECUTION_FAILED"
    for blob in (str(error), str(record)):
        assert "sk-abc123def456" not in blob
        assert "C:\\secret" not in blob
        assert "file.txt" not in blob
    assert error["message"] == "The node failed with an internal RuntimeError."


def test_an_authored_adapter_error_keeps_its_message_but_is_still_sanitized(tmp_path):
    from scriptase.engine.adapters.common import AdapterError

    result = _failing_scheduler(
        tmp_path, AdapterError("SCENES_EMPTY", "No scenes at C:\\projects\\p\\scenes.json")
    )
    error = result.errors["work"]
    assert error["code"] == "SCENES_EMPTY"
    assert "C:\\projects" not in error["message"]
    assert "scenes.json" in error["message"]


def test_a_non_retryable_provider_error_stops_the_attempt_loop(tmp_path):
    """contracts.md §34.3 / D27: three attempts on a bad API key is waste."""
    from scriptase.providers.errors import PROVIDER_AUTH_FAILED, ProviderError

    policy = {"policy": "retry", "max_attempts": 3, "delay_ms": 0, "backoff_multiplier": 1}
    terminal = ProviderError(PROVIDER_AUTH_FAILED, "credentials rejected").as_adapter_error()
    result = _failing_scheduler(tmp_path, terminal, on_error=policy)
    assert result.execution_record["nodes"]["work"]["attempts"] == 1
    assert result.errors["work"]["details"]["provider_code"] == "PROVIDER_AUTH_FAILED"

    retryable = ProviderError("PROVIDER_RATE_LIMITED", "slow down").as_adapter_error()
    retried = _failing_scheduler(tmp_path, retryable, on_error=policy, sleeper=lambda s: None)
    assert retried.execution_record["nodes"]["work"]["attempts"] == 3


def test_a_provider_cancellation_records_the_node_as_cancelled(tmp_path):
    """contracts.md §35.1 / D36: `EXECUTION_CANCELLED` was recognized nowhere."""
    from scriptase.providers.errors import ProviderCancelled

    result = _failing_scheduler(tmp_path, ProviderCancelled().as_adapter_error())
    assert result.node_statuses["work"] == "cancelled"
    assert result.execution_record["nodes"]["work"]["error"]["code"] == "CANCELLED"
    assert "work" not in result.errors


def _cancelling_context():
    return type("Ctx", (), {
        "project_id": "pm_ABC123", "stop_requested": staticmethod(lambda: True),
        "execution_id": "", "node_id": "", "stage_artifact": None,
    })()


SCENES = {"scenes": [{"index": 0, "image_prompt": "a lighthouse"}]}


def test_a_cancelled_storyboard_node_is_recorded_as_cancelled(tmp_path, monkeypatch):
    """contracts.md §35.1: this raised `EXECUTION_CANCELLED` and recorded `failed`."""
    from scriptase.modules.image import generation, jobs as sb_jobs
    from scriptase.engine.adapters import image as storyboard

    monkeypatch.setattr(storyboard, "STORYBOARD_DIR", str(tmp_path / "image"))
    monkeypatch.setattr(sb_jobs, "STORYBOARD_DIR", str(tmp_path / "image"))
    monkeypatch.setattr(generation, "run_batch", lambda *a, **k: None)

    with pytest.raises(Exception) as caught:
        storyboard._step_storyboard(
            SCENES,
            {"storyboard_provider_override": "gemini_ws"},
            "pm_ABC123",
            _cancelling_context(),
        )
    assert caught.value.code == "CANCELLED"


def test_a_cancelled_animator_node_is_recorded_as_cancelled(tmp_path, monkeypatch):
    from scriptase.modules.video import jobs as anim_jobs
    from scriptase.modules.video import ws_runtime as animator_runtime
    from scriptase.engine.adapters import video as animator

    monkeypatch.setattr(animator, "ANIMATOR_DIR", str(tmp_path / "video"))
    monkeypatch.setattr(anim_jobs, "ANIMATOR_DIR", str(tmp_path / "video"))
    monkeypatch.setattr(anim_jobs, "seed", lambda *a, **k: {})
    monkeypatch.setattr(anim_jobs, "read", lambda *a, **k: None)
    monkeypatch.setattr(animator_runtime, "queue_grabber_start", lambda *a, **k: None)
    monkeypatch.setattr(animator_runtime, "is_extension_connected", lambda: True)

    with pytest.raises(Exception) as caught:
        # has_storyboard=True: grok_automa is image_to_video-only (step 6.2
        # capability gate). Cancel is observed after the gate, during the wait.
        animator._step_assets(
            SCENES,
            {"provider_id": "grok_automa"},
            "pm_ABC123",
            _cancelling_context(),
            has_storyboard=True,
        )
    assert caught.value.code == "CANCELLED"


def test_a_cancelled_visual_node_records_cancelled_not_failed(tmp_path):
    """The end-to-end shape: the scheduler recognizes only `CANCELLED`."""
    from scriptase.providers.errors import (
        PROVIDER_TIMEOUT, ProviderCancelled, ProviderError,
    )

    cancelled = _failing_scheduler(tmp_path, ProviderCancelled("x").as_adapter_error())
    assert cancelled.node_statuses["work"] == "cancelled"

    # The timeout code moved from the ad-hoc `NODE_TIMEOUT` to §7's POLL_TIMEOUT.
    timed_out = _failing_scheduler(
        tmp_path, ProviderError(PROVIDER_TIMEOUT, "took too long").as_adapter_error()
    )
    assert timed_out.errors["work"]["code"] == "POLL_TIMEOUT"


def test_a_missing_staged_artifact_reports_only_a_basename(tmp_path):
    """contracts.md §36 L8: the message is persisted into the execution record."""
    workflow = _workflow([_node("root")], [])
    destination = tmp_path / "projects" / "pm_ABC123" / "result.txt"

    def resolver(node):
        def execute(inputs, config, context):
            context.stage_artifact(str(destination))  # staged, never written
            return {"control": {"ok": True}}
        return execute

    result = WorkflowScheduler(
        workflow, project_id="pm_ABC123", lock_root=str(tmp_path / "locks"),
        output_dir=str(tmp_path), executor_resolver=resolver,
    ).run()
    error = result.errors["root"]
    assert error["code"] == "ARTIFACT_MISSING"
    assert error["message"].endswith("result.txt")
    assert str(tmp_path) not in error["message"]
    assert "artifact_" not in error["message"]
