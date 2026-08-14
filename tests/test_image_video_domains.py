"""Step 6.1 — separate image and video domains.

Done when:
  * each domain declares its own capability vocabulary
  * each provider declares capabilities inside that vocabulary
  * an undeclared capability is never offered (catalog / API / selector)
"""

from __future__ import annotations

import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from scriptase.providers.catalog import build_catalog
from scriptase.providers.domains import DOMAINS, SHARED_CAPABILITIES, get_domain
from scriptase.providers.hub import ProviderHub
from scriptase.providers.registry import ProviderManifest
from scriptase.providers.selection import has_capabilities, select_candidates
from scriptase.providers import validation as v


# Routing vocabulary from implementation-plan step 6.1.
IMAGE_ROUTING = frozenset({
    "text_to_image",
    "image_edit",
    "reference_image",
    "inpainting",
})
VIDEO_ROUTING = frozenset({
    "image_to_video",
    "text_to_video",
    "reference_image",
    "duration_control",
})


class ImageVideoVocabularyTests(unittest.TestCase):
    """Each domain owns a closed, distinct routing vocabulary."""

    def test_image_domain_declares_routing_vocabulary(self):
        vocab = DOMAINS["image"].capability_vocabulary
        missing = IMAGE_ROUTING - vocab
        self.assertEqual(missing, set(), f"image missing routing caps: {missing}")
        # Shared platform caps remain available.
        self.assertTrue(SHARED_CAPABILITIES <= vocab)

    def test_video_domain_declares_routing_vocabulary(self):
        vocab = DOMAINS["video"].capability_vocabulary
        missing = VIDEO_ROUTING - vocab
        self.assertEqual(missing, set(), f"video missing routing caps: {missing}")
        self.assertTrue(SHARED_CAPABILITIES <= vocab)

    def test_routing_vocabularies_are_domain_specific(self):
        """text_to_image is image-only; text_to_video / image_to_video are video-only."""
        image = DOMAINS["image"].capability_vocabulary
        video = DOMAINS["video"].capability_vocabulary
        self.assertIn("text_to_image", image)
        self.assertNotIn("text_to_image", video)
        self.assertIn("text_to_video", video)
        self.assertNotIn("text_to_video", image)
        self.assertIn("image_to_video", video)
        self.assertNotIn("image_to_video", image)
        self.assertIn("inpainting", image)
        self.assertNotIn("inpainting", video)


class ShippedProviderCapabilityTests(unittest.TestCase):
    """Every shipped image/video provider declares only vocabulary keys."""

    @classmethod
    def setUpClass(cls):
        cls.hub = ProviderHub()
        for domain in ("image", "video"):
            cls.hub.discover(domain)

    def test_each_provider_capabilities_subset_of_domain_vocabulary(self):
        for domain in ("image", "video"):
            vocab = DOMAINS[domain].capability_vocabulary
            for provider in self.hub.registry(domain).list_providers():
                with self.subTest(domain=domain, provider=provider.id):
                    unknown = set(provider.capabilities) - vocab
                    self.assertEqual(
                        unknown,
                        set(),
                        f"{domain}/{provider.id} declares unknown caps: {unknown}",
                    )
                    # No discovery warnings about unknown capabilities.
                    cap_warnings = [
                        w for w in provider.warnings if "unknown capability" in w
                    ]
                    self.assertEqual(cap_warnings, [])

    def test_image_providers_declare_text_to_image(self):
        for provider in self.hub.registry("image").list_providers():
            with self.subTest(provider=provider.id):
                self.assertTrue(
                    provider.capabilities.get("text_to_image"),
                    f"{provider.id} must declare text_to_image",
                )

    def test_video_providers_declare_at_least_one_motion_mode(self):
        """Every video provider grants image_to_video and/or text_to_video."""
        for provider in self.hub.registry("video").list_providers():
            with self.subTest(provider=provider.id):
                caps = provider.capabilities
                self.assertTrue(
                    caps.get("image_to_video") or caps.get("text_to_video"),
                    f"{provider.id} must declare image_to_video or text_to_video",
                )

    def test_catalog_exposes_vocabulary_and_only_declared_capabilities(self):
        catalog = build_catalog()
        for domain in ("image", "video"):
            with self.subTest(domain=domain):
                payload = catalog[domain]
                self.assertEqual(
                    payload["capability_vocabulary"],
                    sorted(DOMAINS[domain].capability_vocabulary),
                )
                vocab = set(payload["capability_vocabulary"])
                for row in payload["providers"]:
                    offered = {
                        key for key, granted in (row.get("capabilities") or {}).items()
                        if granted is True
                    }
                    self.assertTrue(
                        offered <= vocab,
                        f"{domain}/{row['id']} offers undeclared: {offered - vocab}",
                    )


class UndeclaredCapabilityNeverOfferedTests(unittest.TestCase):
    """An undeclared capability is dropped at validation and never offered."""

    def test_validate_manifest_drops_unknown_capability(self):
        vocab = DOMAINS["image"].capability_vocabulary
        result = v.validate_manifest(
            folder_id="alpha",
            domain="image",
            payload={
                "id": "alpha",
                "label": "Alpha",
                "domain": "image",
                "kind": "cloud",
                "version": "1.0.0",
                "capabilities": {
                    "text_to_image": True,
                    "teleport": True,  # not in vocabulary
                    "batch": True,
                },
            },
            manifest_cls=ProviderManifest,
            capability_vocabulary=vocab,
        )
        self.assertTrue(result.ok)
        self.assertEqual(
            result.manifest.capabilities,
            {"text_to_image": True, "batch": True},
        )
        self.assertIn("unknown capability: teleport", result.warnings)

    def test_selector_never_matches_undeclared_capability(self):
        """Capability query for a key no provider grants returns empty."""
        hub = ProviderHub()
        hub.discover("image")
        hub.discover("video")

        # No shipped image provider grants inpainting yet — must not be offered.
        image_hits = select_candidates(
            "image",
            capabilities=["inpainting"],
            provider_hub=hub,
        )
        self.assertEqual(image_hits, [])

        # text_to_video is video-only; image domain query must not invent it.
        cross = select_candidates(
            "image",
            capabilities=["text_to_video"],
            provider_hub=hub,
        )
        self.assertEqual(cross, [])

        # Undeclared fantasy capability is never offered in either domain.
        for domain in ("image", "video"):
            with self.subTest(domain=domain):
                hits = select_candidates(
                    domain,
                    capabilities=["teleport"],
                    provider_hub=hub,
                )
                self.assertEqual(hits, [])

    def test_has_capabilities_rejects_undeclared_key(self):
        caps = {"text_to_image": True, "batch": True}
        self.assertTrue(has_capabilities(caps, ["text_to_image"]))
        self.assertFalse(has_capabilities(caps, ["inpainting"]))
        self.assertFalse(has_capabilities(caps, ["teleport"]))

    def test_discovered_package_with_unknown_cap_does_not_offer_it(self):
        """A folder that declares a fantasy cap loads without offering it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "alpha").mkdir()
            (root / "alpha" / "manifest.py").write_text(
                textwrap.dedent(
                    """
                    from scriptase.providers import ProviderManifest

                    def manifest():
                        return ProviderManifest(
                            id="alpha",
                            label="Alpha",
                            domain="image",
                            kind="cloud",
                            version="1.0.0",
                            contract_version=2,
                            capabilities={
                                "text_to_image": True,
                                "batch": True,
                                "teleport": True,
                            },
                        )
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            hub = ProviderHub()
            # Point the image registry at the temp tree.
            image_reg = hub.registry("image")
            image_reg.capability_vocabulary = get_domain("image").capability_vocabulary
            snapshot = image_reg.build_snapshot(str(root))
            image_reg.publish(snapshot)
            image_reg._discovered = True

            provider = hub.get("image", "alpha")
            self.assertIsNotNone(provider)
            self.assertNotIn("teleport", provider.capabilities)
            self.assertTrue(provider.capabilities.get("text_to_image"))
            self.assertTrue(
                any("unknown capability: teleport" in w for w in provider.warnings)
            )

            # Selector still cannot offer teleport.
            hits = select_candidates(
                "image",
                capabilities=["teleport"],
                provider_hub=hub,
            )
            self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
