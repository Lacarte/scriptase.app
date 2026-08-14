"""Step 3.3 — capability selector and fallback schema.

Done when:
  * the selector returns correctly ordered candidates for a capability query
  * a persisted fallback chain round-trips through Channel and Job without
    being executed
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scriptase.channels import store as channel_store
from scriptase.channels.models import FallbackPolicy, parse_channel
from scriptase.channels.store import create_channel, default_draft as channel_default_draft
from scriptase.jobs import store as job_store
from scriptase.jobs.snapshot import build_channel_snapshot
from scriptase.jobs.store import create_job, default_draft as job_default_draft, get_job
from scriptase.providers import settings_manager
from scriptase.providers.domains import DomainSpec
from scriptase.providers.hub import ProviderHub
from scriptase.providers.selection import (
    RANK_CATALOG,
    RANK_FALLBACK_CHAIN,
    RANK_FALLBACK_PRIMARY,
    RANK_PREFERRED,
    RANK_SETTINGS,
    has_capabilities,
    normalize_fallback_policy,
    ordered_fallback_ids,
    select_candidates,
    select_first,
)

from test_provider_lifecycle import write_provider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _demo_vocab():
    return frozenset({
        "batch",
        "test_connection",
        "streaming",
        "image_to_video",
        "text_to_video",
        "voice_list",
    })


def _demo_spec(base, domain="demo"):
    return DomainSpec(
        id=domain,
        label="Demo",
        package=f"scriptase.{domain}.providers",
        providers_base=base,
        default_provider="alpha",
        capability_vocabulary=_demo_vocab(),
    )


class CapabilityHelpersTests(unittest.TestCase):
    def test_has_capabilities_require_all_and_any(self):
        caps = {"streaming": True, "batch": False, "voice_list": True}
        self.assertTrue(has_capabilities(caps, ["streaming"]))
        self.assertFalse(has_capabilities(caps, ["streaming", "batch"]))
        self.assertTrue(
            has_capabilities(caps, ["streaming", "batch"], require_all=False)
        )
        self.assertFalse(has_capabilities(caps, ["teleport"]))
        # Empty required = match everything (capability-free query).
        self.assertTrue(has_capabilities(caps, []))
        self.assertTrue(has_capabilities(None, None))

    def test_ordered_fallback_ids_dedupes_and_skips_empty_primary(self):
        self.assertEqual(
            ordered_fallback_ids(
                {"primary": "inst_a", "fallbacks": ["inst_b", "inst_a", "inst_c"]}
            ),
            ["inst_a", "inst_b", "inst_c"],
        )
        self.assertEqual(
            ordered_fallback_ids({"primary": None, "fallbacks": ["inst_b"]}),
            ["inst_b"],
        )
        self.assertEqual(ordered_fallback_ids(None), [])
        self.assertEqual(ordered_fallback_ids({"primary": "", "fallbacks": []}), [])

    def test_normalize_fallback_policy_accepts_model_and_mapping(self):
        model = FallbackPolicy(primary="p1", fallbacks=["p2"])
        self.assertEqual(normalize_fallback_policy(model).primary, "p1")
        self.assertEqual(
            normalize_fallback_policy({"primary": "x", "fallbacks": ["y"]}).fallbacks,
            ["y"],
        )
        self.assertIsNone(normalize_fallback_policy({"primary": None, "fallbacks": []}))


class CapabilitySelectorTests(unittest.TestCase):
    """Selector returns correctly ordered candidates for a capability query."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="scriptase_cap_sel_")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

        # alpha: streaming + batch
        write_provider(
            self.base,
            "alpha",
            domain="demo",
            label="Alpha",
            capabilities={"streaming": True, "batch": True, "voice_list": True},
        )
        # beta: image_to_video only (not streaming)
        write_provider(
            self.base,
            "beta",
            domain="demo",
            label="Beta",
            capabilities={"image_to_video": True, "batch": True},
        )
        # gamma: text_to_video + streaming
        write_provider(
            self.base,
            "gamma",
            domain="demo",
            label="Gamma",
            capabilities={"text_to_video": True, "streaming": True, "batch": True},
        )

        self.hub = ProviderHub(catalog={"demo": _demo_spec(self.base)})
        self.hub.discover("demo")

        self.settings_dir = tempfile.mkdtemp(prefix="scriptase_cap_settings_")
        self.addCleanup(shutil.rmtree, self.settings_dir, ignore_errors=True)
        self.settings_path = os.path.join(self.settings_dir, "settings.json")
        self._settings_patch = patch.object(
            settings_manager, "SETTINGS_PATH", self.settings_path
        )
        self._settings_dir_patch = patch.object(
            settings_manager, "SETTINGS_DIR", self.settings_dir
        )
        self._settings_patch.start()
        self._settings_dir_patch.start()
        self.addCleanup(self._settings_patch.stop)
        self.addCleanup(self._settings_dir_patch.stop)
        # Fresh empty store.
        settings_manager.save_settings({
            "version": settings_manager.SETTINGS_VERSION
            if hasattr(settings_manager, "SETTINGS_VERSION")
            else 6,
            "general": {},
            "domains": {
                "demo": {"selected_instance_id": None, "instances": {}},
            },
        })

    def _seed_instances(self):
        """Two instances of alpha, one of beta; select the secondary alpha."""
        settings_manager.upsert_instance(
            "demo",
            provider_type="alpha",
            instance_id="alpha",
            label="Alpha Default",
            settings={"api_key": "k-main"},
        )
        settings_manager.upsert_instance(
            "demo",
            provider_type="alpha",
            instance_id="alpha_backup",
            label="Alpha Backup",
            settings={"api_key": "k-backup"},
        )
        settings_manager.upsert_instance(
            "demo",
            provider_type="beta",
            instance_id="beta_main",
            label="Beta Main",
            settings={},
        )
        settings_manager.set_selected_instance("demo", "alpha_backup")

    def test_capability_query_filters_and_orders_by_catalog(self):
        # No policy, no selection: catalog order of matching types as default ids.
        candidates = select_candidates(
            "demo",
            capabilities=["streaming"],
            provider_hub=self.hub,
        )
        ids = [c.instance_id for c in candidates]
        # alpha and gamma grant streaming; beta does not.
        self.assertEqual(ids, ["alpha", "gamma"])
        self.assertTrue(all(c.rank_reason == RANK_CATALOG for c in candidates))
        self.assertTrue(all(c.capabilities.get("streaming") is True for c in candidates))

    def test_selected_instance_ranks_before_catalog_peers(self):
        self._seed_instances()
        candidates = select_candidates(
            "demo",
            capabilities=["streaming"],
            provider_hub=self.hub,
        )
        ids = [c.instance_id for c in candidates]
        # Selected alpha_backup first, then remaining alpha instance, then gamma.
        self.assertEqual(ids[0], "alpha_backup")
        self.assertEqual(candidates[0].rank_reason, RANK_SETTINGS)
        self.assertIn("alpha", ids)
        self.assertIn("gamma", ids)
        self.assertNotIn("beta_main", ids)  # no streaming

    def test_fallback_policy_orders_primary_then_fallbacks(self):
        self._seed_instances()
        # Also create a gamma instance so policy can name it.
        settings_manager.upsert_instance(
            "demo",
            provider_type="gamma",
            instance_id="gamma_cloud",
            label="Gamma Cloud",
            settings={"api_key": "g"},
        )
        policy = {
            "primary": "gamma_cloud",
            "fallbacks": ["alpha_backup", "alpha"],
        }
        candidates = select_candidates(
            "demo",
            capabilities=["streaming"],
            fallback_policy=policy,
            provider_hub=self.hub,
        )
        ids = [c.instance_id for c in candidates]
        self.assertEqual(ids[:3], ["gamma_cloud", "alpha_backup", "alpha"])
        self.assertEqual(candidates[0].rank_reason, RANK_FALLBACK_PRIMARY)
        self.assertEqual(candidates[0].chain_index, 0)
        self.assertEqual(candidates[1].rank_reason, RANK_FALLBACK_CHAIN)
        self.assertEqual(candidates[1].chain_index, 1)
        self.assertEqual(candidates[2].rank_reason, RANK_FALLBACK_CHAIN)
        self.assertEqual(candidates[2].chain_index, 2)

    def test_policy_entry_for_incapable_type_is_skipped(self):
        self._seed_instances()
        candidates = select_candidates(
            "demo",
            capabilities=["streaming"],
            fallback_policy={
                "primary": "beta_main",  # beta has no streaming
                "fallbacks": ["alpha"],
            },
            provider_hub=self.hub,
        )
        ids = [c.instance_id for c in candidates]
        self.assertNotIn("beta_main", ids)
        self.assertEqual(ids[0], "alpha")
        self.assertEqual(candidates[0].rank_reason, RANK_FALLBACK_CHAIN)
        self.assertEqual(candidates[0].chain_index, 1)

    def test_preferred_instance_ranks_after_policy_before_selection(self):
        self._seed_instances()
        settings_manager.upsert_instance(
            "demo",
            provider_type="gamma",
            instance_id="gamma_cloud",
            label="Gamma Cloud",
            settings={},
        )
        candidates = select_candidates(
            "demo",
            capabilities=["streaming"],
            fallback_policy={"primary": "alpha", "fallbacks": []},
            preferred_instance_id="gamma_cloud",
            provider_hub=self.hub,
        )
        ids = [c.instance_id for c in candidates]
        self.assertEqual(ids[0], "alpha")
        self.assertEqual(candidates[0].rank_reason, RANK_FALLBACK_PRIMARY)
        self.assertEqual(ids[1], "gamma_cloud")
        self.assertEqual(candidates[1].rank_reason, RANK_PREFERRED)
        # Selected alpha_backup still appears later, not before preferred.
        self.assertIn("alpha_backup", ids)
        self.assertGreater(ids.index("alpha_backup"), ids.index("gamma_cloud"))

    def test_require_all_false_matches_any_capability(self):
        candidates = select_candidates(
            "demo",
            capabilities=["streaming", "image_to_video"],
            require_all=False,
            provider_hub=self.hub,
        )
        types = {c.provider_type for c in candidates}
        self.assertEqual(types, {"alpha", "beta", "gamma"})

    def test_require_all_true_needs_every_capability(self):
        # Nothing grants both streaming and image_to_video.
        candidates = select_candidates(
            "demo",
            capabilities=["streaming", "image_to_video"],
            require_all=True,
            provider_hub=self.hub,
        )
        self.assertEqual(candidates, [])

    def test_channel_snapshot_supplies_policy_and_defaults(self):
        self._seed_instances()
        settings_manager.upsert_instance(
            "demo",
            provider_type="gamma",
            instance_id="gamma_cloud",
            settings={},
        )
        snapshot = {
            "provider_defaults": {"demo": "alpha"},
            "fallback_policies": {
                "demo": {
                    "primary": "gamma_cloud",
                    "fallbacks": ["alpha_backup"],
                }
            },
        }
        candidates = select_candidates(
            "demo",
            capabilities=["streaming"],
            channel_snapshot=snapshot,
            stage="demo",
            provider_hub=self.hub,
        )
        ids = [c.instance_id for c in candidates]
        self.assertEqual(ids[0], "gamma_cloud")
        self.assertEqual(ids[1], "alpha_backup")
        # provider_defaults preferred comes after the policy chain.
        self.assertIn("alpha", ids)
        self.assertEqual(
            candidates[ids.index("alpha")].rank_reason, RANK_PREFERRED
        )

    def test_select_first_and_empty_domain(self):
        first = select_first(
            "demo",
            capabilities=["image_to_video"],
            provider_hub=self.hub,
        )
        self.assertIsNotNone(first)
        self.assertEqual(first.provider_type, "beta")

        self.assertIsNone(
            select_first("no_such_domain", capabilities=["batch"], provider_hub=self.hub)
        )
        self.assertEqual(
            select_candidates(
                "demo",
                capabilities=["teleport"],
                provider_hub=self.hub,
            ),
            [],
        )

    def test_candidate_to_dict_is_secret_free(self):
        self._seed_instances()
        candidates = select_candidates(
            "demo",
            capabilities=["streaming"],
            provider_hub=self.hub,
        )
        payload = candidates[0].to_dict()
        serialized = str(payload)
        self.assertNotIn("api_key", serialized)
        self.assertNotIn("k-main", serialized)
        self.assertNotIn("k-backup", serialized)
        self.assertIn("instance_id", payload)
        self.assertIn("rank_reason", payload)


class FallbackChainRoundTripTests(unittest.TestCase):
    """Persisted fallback chain round-trips Channel → Job without execution."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_fallback_rt_")
        self.addCleanup(self.temp.cleanup)

        self.old_channels = channel_store._channels_dir
        self.old_channel_trash = channel_store._trash_dir
        channel_store._channels_dir = os.path.join(self.temp.name, "channels")
        channel_store._trash_dir = os.path.join(self.temp.name, "trash", "channels")
        os.makedirs(channel_store._channels_dir, exist_ok=True)
        self.addCleanup(self._restore_channels)

        self.old_jobs = job_store._jobs_dir
        self.old_job_trash = job_store._trash_dir
        job_store._jobs_dir = os.path.join(self.temp.name, "jobs")
        job_store._trash_dir = os.path.join(self.temp.name, "trash", "jobs")
        os.makedirs(job_store._jobs_dir, exist_ok=True)
        self.addCleanup(self._restore_jobs)

    def _restore_channels(self):
        channel_store._channels_dir = self.old_channels
        channel_store._trash_dir = self.old_channel_trash

    def _restore_jobs(self):
        job_store._jobs_dir = self.old_jobs
        job_store._trash_dir = self.old_job_trash

    def _channel_draft(self):
        draft = channel_default_draft(name="Fallback Channel")
        draft["provider_defaults"] = {
            "image": "inst_image_primary",
            "video": "inst_video_primary",
            "tts": "inst_tts_1",
        }
        draft["fallback_policies"] = {
            "image": {
                "primary": "inst_image_primary",
                "fallbacks": ["inst_image_backup", "inst_image_last"],
            },
            "video": {
                "primary": "inst_video_primary",
                "fallbacks": ["inst_video_backup"],
            },
            "tts": {
                "primary": "inst_tts_1",
                "fallbacks": [],
            },
        }
        return draft

    def test_channel_persists_and_reloads_fallback_policies(self):
        channel = create_channel(self._channel_draft())
        self.assertIn("image", channel.fallback_policies)
        image_policy = channel.fallback_policies["image"]
        self.assertIsInstance(image_policy, FallbackPolicy)
        self.assertEqual(image_policy.primary, "inst_image_primary")
        self.assertEqual(
            image_policy.fallbacks, ["inst_image_backup", "inst_image_last"]
        )
        self.assertEqual(
            ordered_fallback_ids(image_policy),
            ["inst_image_primary", "inst_image_backup", "inst_image_last"],
        )

        # On-disk document round-trips through parse_channel.
        path = os.path.join(channel_store._channels_dir, f"{channel.id}.json")
        import json

        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        reparsed = parse_channel(raw)
        self.assertEqual(
            ordered_fallback_ids(reparsed.fallback_policies["image"]),
            ["inst_image_primary", "inst_image_backup", "inst_image_last"],
        )
        self.assertEqual(
            ordered_fallback_ids(reparsed.fallback_policies["video"]),
            ["inst_video_primary", "inst_video_backup"],
        )
        self.assertEqual(
            ordered_fallback_ids(reparsed.fallback_policies["tts"]),
            ["inst_tts_1"],
        )

    def test_job_snapshot_freezes_chain_without_executing(self):
        channel = create_channel(self._channel_draft())
        job = create_job(
            job_default_draft(
                channel_id=channel.id,
                execution_mode="manual",
                source={"mode": "idea", "idea": "test fallback freeze"},
            )
        )

        snapshot = job.channel_snapshot
        self.assertIsInstance(snapshot, dict)
        self.assertEqual(
            snapshot["fallback_policies"]["image"]["primary"],
            "inst_image_primary",
        )
        self.assertEqual(
            snapshot["fallback_policies"]["image"]["fallbacks"],
            ["inst_image_backup", "inst_image_last"],
        )
        self.assertEqual(
            snapshot["fallback_policies"]["video"]["fallbacks"],
            ["inst_video_backup"],
        )
        # Instance references only — no credentials.
        serialized = str(snapshot)
        for banned in ("api_key", "password", "client_secret", "token"):
            self.assertNotIn(banned, serialized.lower())

        # Process restart: reload Job and the chain is intact.
        reloaded = get_job(job.id)
        self.assertEqual(
            reloaded.channel_snapshot["fallback_policies"]["image"],
            {
                "primary": "inst_image_primary",
                "fallbacks": ["inst_image_backup", "inst_image_last"],
            },
        )
        # build_channel_snapshot is pure — re-freezing matches.
        rebuilt = build_channel_snapshot(channel)
        self.assertEqual(
            rebuilt["fallback_policies"]["image"]["fallbacks"],
            reloaded.channel_snapshot["fallback_policies"]["image"]["fallbacks"],
        )

        # Selector can read the frozen chain for ordering without invoking providers.
        chain = ordered_fallback_ids(
            reloaded.channel_snapshot["fallback_policies"]["image"]
        )
        self.assertEqual(
            chain,
            ["inst_image_primary", "inst_image_backup", "inst_image_last"],
        )


if __name__ == "__main__":
    unittest.main()
