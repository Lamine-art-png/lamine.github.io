"""Unit tests for CropSoilProfile — pure lookup, no DB."""
import pytest

from app.services.crop_soil_profile import (
    CropSoilProfile,
    DEFAULT_PROFILE,
    get_profile,
    list_profiles,
)


class TestGetProfile:
    def test_exact_match_corn_loam(self):
        p = get_profile("corn", "loam")
        assert p.crop_type == "corn"
        assert p.soil_type == "loam"
        assert p.field_capacity == 0.36
        assert p.kc == 1.15

    def test_exact_match_vineyard_clay(self):
        p = get_profile("vineyard", "clay")
        assert p.crop_type == "vineyard"
        assert p.soil_type == "clay"
        assert p.kc == 0.70

    def test_case_insensitive(self):
        p = get_profile("CORN", "LOAM")
        assert p.crop_type == "corn"
        assert p.soil_type == "loam"

    def test_unknown_soil_falls_back_to_crop(self):
        p = get_profile("corn", "peat")
        assert p.crop_type == "corn"
        # Should return some corn profile (first match)

    def test_unknown_crop_falls_back_to_soil(self):
        p = get_profile("rice", "loam")
        # Should find a profile with loam soil
        assert p.soil_type == "loam"

    def test_completely_unknown_returns_default(self):
        p = get_profile("rice", "peat")
        assert p == DEFAULT_PROFILE

    def test_none_crop_none_soil_returns_default(self):
        p = get_profile(None, None)
        assert p == DEFAULT_PROFILE

    def test_none_crop_valid_soil(self):
        p = get_profile(None, "clay")
        assert p.soil_type == "clay"

    def test_valid_crop_none_soil(self):
        p = get_profile("wheat", None)
        assert p.crop_type == "wheat"


class TestDefaultProfile:
    def test_default_has_sensible_values(self):
        assert DEFAULT_PROFILE.field_capacity > DEFAULT_PROFILE.stress_threshold
        assert DEFAULT_PROFILE.stress_threshold > DEFAULT_PROFILE.wilting_point
        assert DEFAULT_PROFILE.saturation > DEFAULT_PROFILE.field_capacity
        assert 0 < DEFAULT_PROFILE.kc <= 2.0
        assert DEFAULT_PROFILE.root_depth_mm > 0
        assert 0 < DEFAULT_PROFILE.mad < 1


class TestProfileConsistency:
    def test_all_profiles_have_valid_ranges(self):
        profiles = list_profiles()
        assert len(profiles) >= 18  # 6 crops × 3 soil types minimum

        for p in profiles:
            assert p["wilting_point"] < p["stress_threshold"]
            assert p["stress_threshold"] < p["field_capacity"]
            assert p["field_capacity"] < p["saturation"]
            assert p["root_depth_mm"] > 0
            assert 0 < p["mad"] < 1
            assert 0 < p["kc"] <= 2.0

    def test_clay_has_higher_field_capacity_than_sand(self):
        corn_clay = get_profile("corn", "clay")
        corn_sand = get_profile("corn", "sand")
        assert corn_clay.field_capacity > corn_sand.field_capacity

    def test_trees_have_deeper_roots_than_vegetables(self):
        trees = get_profile("trees", "loam")
        vegs = get_profile("vegetables", "loam")
        assert trees.root_depth_mm > vegs.root_depth_mm


class TestListProfiles:
    def test_returns_list_of_dicts(self):
        profiles = list_profiles()
        assert isinstance(profiles, list)
        assert len(profiles) > 0
        assert all("crop_type" in p for p in profiles)
        assert all("kc" in p for p in profiles)


class TestFrozenProfile:
    def test_profile_is_immutable(self):
        p = get_profile("corn", "loam")
        with pytest.raises(AttributeError):
            p.field_capacity = 0.99
