from scriptase.modules.pipeline.services import _step_segment
from .common import outputs, project_id, with_artifacts


def run(inputs, config, context):
    pid = project_id(context, inputs)
    result = _step_segment(inputs["alignment"], dict(config or {}), pid)
    return outputs(segments=with_artifacts(result, result["output_path"]))
