"""Job: one video-production run, plus the stage projection of its workflow.

Populated in steps 1.4, 1.5, and 2.2. A Job wraps ``execution_manager.start()``;
it does not become a node. Job status derives from the execution record rather
than being tracked separately, so the two can never disagree.

The ordered stage list is *computed from the graph* here on the backend — a
hardcoded step array in the frontend would silently diverge the first time a
branch is added.
"""
