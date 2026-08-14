"""Thin ``(inputs, config, context) -> outputs`` adapters bridging nodes to modules.

Populated in step 0.3. Hard rule (audited by test in 0.3): no adapter may place
an absolute filesystem path into a port payload — managed relative references
only.
"""
