"""One-off: ffprobe the live-run export to confirm playable video+audio."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from studio.ffmpeg_utils import find_ffprobe

path = sys.argv[1] if len(sys.argv) > 1 else "output/exports/pm_HI6LNE_2b9e5668.mp4"
p = subprocess.run(
    [find_ffprobe(), "-v", "quiet", "-print_format", "json",
     "-show_format", "-show_streams", path],
    capture_output=True, text=True, check=True,
)
d = json.loads(p.stdout)
streams = {s["codec_type"]: (s.get("width"), s.get("height"), s.get("codec_name"))
           for s in d["streams"]}
print("streams:", streams)
print("duration:", d["format"]["duration"])
