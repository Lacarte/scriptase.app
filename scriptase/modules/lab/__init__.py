"""Prompt Lab — transparency, testing, and (later) measurement for script prompts.

The Lab is where the script prompt engineering — normally buried in
`scriptase.modules.script.prompts` — becomes visible and inspectable: what
system/user prompt produced a given script, decomposed into its parts, and a
preview of what a set of inputs *would* produce without running a full job.
"""

from scriptase.modules.lab.routes import lab_bp

__all__ = ["lab_bp"]
