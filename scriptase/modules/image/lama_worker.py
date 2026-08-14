"""LaMa inpainting worker — runs inside an isolated venv.

This script is launched by `lama_client.py` as a long-lived subprocess and
communicates over stdin/stdout using newline-delimited JSON. It loads the
LaMa model once and reuses it across many jobs in the same pipeline run.

Why isolated: simple-lama-inpainting depends on numpy<2 and torch 2.11
which conflict with the rest of the project (numpy 2.x, torch 2.10).
We isolate it in `_dev/venvs/lama/` and bridge via subprocess + JSON.

Protocol:
    Input  (per line): {"in": "/path/to/image.jpg", "mask": "/path/to/mask.png", "out": "/path/to/result.jpg"}
    Output (per line): {"ok": true} | {"ok": false, "error": "..."}

Special command:
    {"cmd": "ping"}  -> {"ok": true, "ready": true}
    {"cmd": "quit"}  -> graceful shutdown
"""
import json
import sys
import traceback


def _emit(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main():
    # Lazy import — keeps "ping" path fast and lets us emit a ready message
    # before the heavy model load.
    try:
        from PIL import Image
        from simple_lama_inpainting import SimpleLama
    except Exception as exc:  # pragma: no cover
        _emit({"ok": False, "error": f"import failed: {exc}"})
        return 1

    try:
        lama = SimpleLama()
    except Exception as exc:  # pragma: no cover
        _emit({"ok": False, "error": f"model load failed: {exc}\n{traceback.format_exc()}"})
        return 1

    _emit({"ok": True, "ready": True})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            job = json.loads(line)
        except json.JSONDecodeError as exc:
            _emit({"ok": False, "error": f"invalid json: {exc}"})
            continue

        cmd = job.get("cmd")
        if cmd == "ping":
            _emit({"ok": True, "ready": True})
            continue
        if cmd == "quit":
            _emit({"ok": True, "bye": True})
            return 0

        try:
            in_path = job["in"]
            mask_path = job["mask"]
            out_path = job["out"]
            image = Image.open(in_path).convert("RGB")
            mask = Image.open(mask_path).convert("L")
            result = lama(image, mask)
            # Preserve format if possible
            ext = out_path.rsplit(".", 1)[-1].lower()
            save_kwargs = {}
            if ext in ("jpg", "jpeg"):
                save_kwargs = {"quality": 100, "subsampling": 0}
            result.save(out_path, **save_kwargs)
            _emit({"ok": True})
        except Exception as exc:
            _emit({"ok": False, "error": f"{exc}\n{traceback.format_exc()}"})

    return 0


if __name__ == "__main__":
    sys.exit(main())
