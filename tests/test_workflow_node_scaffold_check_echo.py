"""Generated smoke tests for scaffold_check.echo."""

from scriptase.engine.adapters.generated.scaffold_check_echo import execute
from scriptase.engine.registry import get_node_type, serialize_registry


def test_scaffold_check_echo_is_registered_and_palette_visible():
    definition = get_node_type("scaffold_check.echo")
    assert definition is not None
    assert "scaffold_check.echo" in serialize_registry()["node_types"]


def test_scaffold_check_echo_executes_with_the_declared_outputs():
    result = execute({}, {"value": {"generated": True}}, {})
    assert set(result) == set(["control", "result"])
    assert result["control"] == {"ok": True}


def test_scaffold_check_echo_prefers_a_connected_source():
    result = execute(
        {"source": {"from": "edge"}},
        {"value": {"from": "configuration"}},
        {},
    )
    assert result["result"] == {"from": "edge"}
