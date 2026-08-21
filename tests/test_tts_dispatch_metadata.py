"""Regression: `dispatch.synthesize` builds metadata with the resolved provider.

The non-cache path once passed `instance=instance` to `_metadata`, but the
variable holding the provider package is `package` — `instance` was never
defined, so every first-time (non-cached) synthesis crashed with a NameError
before writing its sidecar. Both call sites must pass `package`.
"""

from __future__ import annotations

import ast
import inspect
import unittest

from scriptase.modules.tts import dispatch


class SynthesizeNameResolutionTests(unittest.TestCase):
    def test_synthesize_never_references_an_undefined_instance(self):
        """No bare `instance` name in `synthesize` — only `package`/`instance_id`.

        A NameError in a node executor surfaces to the user as an opaque
        "internal NameError" job failure, so it must be caught statically.
        """
        source = inspect.getsource(dispatch.synthesize)
        tree = ast.parse(source)

        # Names bound in the function (params, assignments, comprehensions).
        bound: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.arg):
                bound.add(node.arg)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                bound.add(node.id)

        offenders = [
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id == "instance"
            and "instance" not in bound
        ]
        self.assertEqual(
            offenders,
            [],
            "synthesize() loads a bare `instance` that is never bound — "
            "use `package` (the resolved provider) instead.",
        )


if __name__ == "__main__":
    unittest.main()
