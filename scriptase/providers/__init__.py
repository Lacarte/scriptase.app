"""Provider plugin platform: discovery, invocation, error taxonomy, redaction.

Populated in step 0.2 from V2's ``studio/shared/providers_common/`` plus the
provider routes. Domain ids rename with the packages
(``scene_blueprint``->``scene_director``, ``storyboard``->``image``,
``animator``->``video``); domains are data in ``providers/domains.py``.

Adding a provider means creating and registering its package alone — a provider
may never modify a node definition, adapter, route, or generic UI component.
"""
