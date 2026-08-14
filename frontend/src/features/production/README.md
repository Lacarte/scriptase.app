# production

The step/window Production view (Phase 2, steps 2.3–2.5).

It renders the ordered stage list returned by the backend stage-projection
endpoint (step 2.2) and consumes the **same** SSE stream the workflow canvas
uses — including its ring-buffer reset snapshot and `Last-Event-ID` resume.

Do not hardcode a step array here, and do not add a second polling mechanism.
Either one silently diverges the two views the first time a branch is added.
