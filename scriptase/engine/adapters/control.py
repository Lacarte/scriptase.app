from .common import CONTROL


def manual_trigger(inputs, config, context):
    return {"control": CONTROL}


def workflow_output(inputs, config, context):
    return {"value": inputs["value"], "label": (config or {}).get("label", "")}
