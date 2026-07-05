"""Tests for spindle.capabilities — unit + integration.

Unit tests use a fake package list so they are hermetic.
Integration tests (marked with the `live` suffix) rely on the
real sample-* editable installs and verify that capabilities trace
back to a peer source with a non-empty peer name and URL.
"""

from __future__ import annotations

import dataclasses
import datetime
from unittest.mock import patch

import pytest

from spindle import capabilities as caps_module
from spindle.capabilities import list_capabilities, show_capability
from spindle.models import PackageMetadata, Source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pkg(
    name: str,
    cap_list: list[str],
    sources: list[Source] | None = None,
) -> PackageMetadata:
    return PackageMetadata(
        name=name,
        version="1.0.0",
        distribution="spindle-sample",
        skills=[],
        capabilities=cap_list,
        sources=sources or [],
        package_dir=f"/fake/{name}",
    )


_SOURCE_A = Source(
    peer="acme/alpha-skills",
    url="https://github.com/acme/alpha-skills",
    transposed_at=datetime.date(2025, 6, 1),
    notes="origin of cap-alpha",
)
_SOURCE_B = Source(
    peer="widget-corp/widgets",
    url="https://github.com/widget-corp/widgets",
    transposed_at=datetime.date(2025, 9, 15),
    notes="",
)

_FAKE_PKGS = [
    _make_pkg("sample-alpha", ["cap-alpha", "cap-shared"], [_SOURCE_A]),
    _make_pkg("sample-beta", ["cap-beta", "cap-shared"], [_SOURCE_B]),
    _make_pkg("sample-empty", [], []),
]


# ---------------------------------------------------------------------------
# list_capabilities — unit
# ---------------------------------------------------------------------------

class TestListCapabilities:
    def _call(self):
        with patch.object(caps_module, "list_installed_packages", return_value=_FAKE_PKGS):
            return list_capabilities()

    def test_returns_dict(self):
        result = self._call()
        assert isinstance(result, dict)

    def test_all_capabilities_present(self):
        result = self._call()
        assert set(result) == {"cap-alpha", "cap-shared", "cap-beta"}

    def test_single_provider(self):
        result = self._call()
        assert result["cap-alpha"] == ["sample-alpha"]
        assert result["cap-beta"] == ["sample-beta"]

    def test_shared_capability_lists_both_packages(self):
        result = self._call()
        assert "sample-alpha" in result["cap-shared"]
        assert "sample-beta" in result["cap-shared"]

    def test_package_with_no_capabilities_omitted(self):
        result = self._call()
        for providers in result.values():
            assert "sample-empty" not in providers

    def test_empty_environment(self):
        with patch.object(caps_module, "list_installed_packages", return_value=[]):
            result = list_capabilities()
        assert result == {}


# ---------------------------------------------------------------------------
# show_capability — unit
# ---------------------------------------------------------------------------

class TestShowCapability:
    def _call(self, name: str):
        with patch.object(caps_module, "list_installed_packages", return_value=_FAKE_PKGS):
            return show_capability(name)

    def test_returns_dict_with_required_keys(self):
        result = self._call("cap-alpha")
        assert {"name", "packages", "sources"} == set(result)

    def test_name_field_echoes_input(self):
        result = self._call("cap-alpha")
        assert result["name"] == "cap-alpha"

    def test_packages_lists_provider(self):
        result = self._call("cap-alpha")
        assert result["packages"] == ["sample-alpha"]

    def test_sources_trace_to_peer(self):
        result = self._call("cap-alpha")
        assert len(result["sources"]) == 1
        src = result["sources"][0]
        assert src["peer"] == "acme/alpha-skills"
        assert src["url"] == "https://github.com/acme/alpha-skills"
        assert src["transposed_at"] == datetime.date(2025, 6, 1)
        assert src["notes"] == "origin of cap-alpha"

    def test_sources_are_plain_dicts(self):
        result = self._call("cap-alpha")
        for src in result["sources"]:
            assert isinstance(src, dict)

    def test_shared_capability_has_two_packages_and_two_sources(self):
        result = self._call("cap-shared")
        assert set(result["packages"]) == {"sample-alpha", "sample-beta"}
        peers = {s["peer"] for s in result["sources"]}
        assert peers == {"acme/alpha-skills", "widget-corp/widgets"}

    def test_source_with_empty_notes_included(self):
        result = self._call("cap-beta")
        assert len(result["sources"]) == 1
        assert result["sources"][0]["notes"] == ""

    def test_unknown_capability_returns_empty_packages_and_sources(self):
        result = self._call("does-not-exist")
        assert result["name"] == "does-not-exist"
        assert result["packages"] == []
        assert result["sources"] == []

    def test_source_dict_matches_dataclass_fields(self):
        """Verify show_capability serialises via dataclasses.asdict, not ad-hoc."""
        result = self._call("cap-alpha")
        expected_keys = {f.name for f in dataclasses.fields(Source)}
        assert set(result["sources"][0]) == expected_keys


# ---------------------------------------------------------------------------
# Integration — traces capability back to peer source (live sample-* install)
# ---------------------------------------------------------------------------

class TestLiveCapabilityTrace:
    """These tests require the sample-* packages to be editably installed."""

    def test_list_capabilities_non_empty(self):
        result = list_capabilities()
        assert len(result) > 0, "No capabilities found — are sample-* packages installed?"

    def test_every_capability_has_at_least_one_package(self):
        result = list_capabilities()
        for cap, providers in result.items():
            assert len(providers) > 0, f"Capability '{cap}' has no providers"

    def test_requirements_clarification_traces_to_peer(self):
        """requirements-clarification must resolve to a non-empty peer/URL."""
        result = show_capability("requirements-clarification")
        assert "sample-planning" in result["packages"]
        assert len(result["sources"]) > 0, "requirements-clarification has no sources"
        for src in result["sources"]:
            assert src["peer"], "source peer must be non-empty"
            assert src["url"], "source url must be non-empty"
            assert src["transposed_at"], "source transposed_at must be set"

    def test_all_live_capabilities_have_source_with_peer(self):
        """Every capability provided by a real sample-* package traces to at least one peer."""
        cap_map = list_capabilities()
        missing_source: list[str] = []
        empty_peer: list[str] = []

        for cap_name in cap_map:
            detail = show_capability(cap_name)
            if not detail["sources"]:
                missing_source.append(cap_name)
                continue
            for src in detail["sources"]:
                if not src.get("peer"):
                    empty_peer.append(cap_name)

        assert missing_source == [], f"Capabilities with no sources: {missing_source}"
        assert empty_peer == [], f"Capabilities with empty peer: {empty_peer}"

    def test_show_plan_review_traces_to_peer(self):
        """plan-review has peer provenance."""
        result = show_capability("plan-review")
        assert "sample-planning" in result["packages"]
        assert len(result["sources"]) > 0
        for src in result["sources"]:
            assert src["peer"]
            assert src["url"]
