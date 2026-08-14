def sample_input(inputs, config, context):
    return {"value": (config or {}).get("payload")}


def result_viewer(inputs, config, context):
    return {"value": inputs.get("value")}
