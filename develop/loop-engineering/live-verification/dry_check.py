"""Dry validation of the live-run workflow document (no providers touched)."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from studio.workflows.execution import prepare_snapshot, resolve_scope
from studio.workflows.templates import full_video_template

document = full_video_template()
document.pop("template_id", None)
nodes = {node["id"]: node for node in document["nodes"]}
nodes["n_script"]["configuration"]["text"] = "Dry-run script text."
nodes["n_setup"]["configuration"]["tone"] = "educational"
nodes["n_setup"]["configuration"]["project_name"] = "Live verification"
nodes["n_animator"]["configuration"]["provider"] = "kie_ai"
nodes["n_animator"]["configuration"]["mode"] = "image"

snapshot = prepare_snapshot(document)
scope = resolve_scope(snapshot, "full", [])
print("validation OK; scope:", scope)
