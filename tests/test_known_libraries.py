"""Unit tests for the known libraries database.

Tests R-015 library metadata.
"""

from __future__ import annotations

import pytest

from codegraph.known_libraries import (
    LibraryInfo,
    get_library_info,
    get_all_known_names,
    get_libraries_by_category,
    enrich_side_effects_from_library,
    enrich_domain_tags_from_library,
)
from codegraph.models.graph2 import SideEffectType


class TestLibraryInfo:

    def test_dataclass_fields(self) -> None:
        info = LibraryInfo(name="test", category="testing")
        assert info.name == "test"
        assert info.category == "testing"

    def test_frozen(self) -> None:
        info = LibraryInfo(name="test", category="testing")
        with pytest.raises(AttributeError):
            info.name = "changed"  # type: ignore[misc]


class TestGetLibraryInfo:

    def test_known_library(self) -> None:
        info = get_library_info("requests")
        assert info is not None
        assert info.name == "requests"
        assert info.category == "http"

    def test_unknown_library(self) -> None:
        info = get_library_info("totally_unknown_lib_xyz")
        assert info is None

    def test_sqlalchemy(self) -> None:
        info = get_library_info("sqlalchemy")
        assert info is not None
        assert info.category == "database"

    def test_flask(self) -> None:
        info = get_library_info("flask")
        assert info is not None
        assert info.category == "web"


class TestGetAllKnownNames:

    def test_returns_set(self) -> None:
        names = get_all_known_names()
        assert isinstance(names, set)
        assert len(names) > 30  # should have 50+ libraries

    def test_contains_major_libs(self) -> None:
        names = get_all_known_names()
        for lib in ("requests", "flask", "django", "pytest", "os", "json"):
            assert lib in names


class TestGetLibrariesByCategory:

    def test_http_category(self) -> None:
        libs = get_libraries_by_category("http")
        assert len(libs) >= 1
        assert all(lib.category == "http" for lib in libs)

    def test_database_category(self) -> None:
        libs = get_libraries_by_category("database")
        assert len(libs) >= 2

    def test_empty_category(self) -> None:
        libs = get_libraries_by_category("nonexistent_category")
        assert libs == []


class TestEnrichSideEffects:

    def test_requests_side_effects(self) -> None:
        effects = enrich_side_effects_from_library("requests")
        assert SideEffectType.NETWORK_CALL in effects

    def test_unknown_returns_empty(self) -> None:
        effects = enrich_side_effects_from_library("unknown_lib")
        assert effects == []


class TestEnrichDomainTags:

    def test_flask_tags(self) -> None:
        tags = enrich_domain_tags_from_library("flask")
        assert len(tags) >= 1

    def test_unknown_returns_empty(self) -> None:
        tags = enrich_domain_tags_from_library("unknown_lib")
        assert tags == []
