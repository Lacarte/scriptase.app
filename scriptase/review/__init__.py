"""Review and the Repair Router (Phases 7 and 8).

Deterministic technical validators run first; expensive AI review is never the
only validation layer. Review returns only structured ``ReviewIssue`` records —
free-form text is not an acceptable review output, because automation depends on
structure.

The Repair Router sends each issue back to the node responsible for fixing it
via a table-driven policy, and repairs the smallest responsible scope.
"""
