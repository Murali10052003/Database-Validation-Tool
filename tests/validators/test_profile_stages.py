import pytest

from app.core.config import DataValidationConfig, ValidationConfig
from app.core.enums import ValidationProfile
from app.schemas.api import MigrationRequest
from app.validators.engine import ValidationEngine


@pytest.mark.parametrize("profile", list(ValidationProfile))
def test_profiles_do_not_run_sample_data(profile):
    assert "sample_data" not in ValidationEngine.selected_stages(profile)
    assert "sample_data" not in ValidationEngine()._registry


def test_full_profile_keeps_checksum_and_aggregates():
    stages = ValidationEngine.selected_stages(ValidationProfile.FULL)
    assert "checksum" in stages
    assert "aggregate" in stages


def test_sampling_is_not_an_active_configuration_option():
    assert "sample_size" not in DataValidationConfig.model_fields


def test_default_checksum_row_limit():
    assert DataValidationConfig().chunk_size == 100


def test_custom_selection_keeps_prerequisites_and_canonical_order():
    assert ValidationEngine.selected_stages(
        ValidationProfile.CUSTOM, ["checksum", "row_count", "row_count"],
    ) == ["connectivity", "discovery", "row_count", "checksum"]


@pytest.mark.parametrize("selection", [[], ["unknown"], ["connectivity"]])
def test_invalid_selection_rejected(selection):
    with pytest.raises(ValueError):
        ValidationConfig(selected_checks=selection)
    with pytest.raises(ValueError):
        ValidationEngine.selected_stages(ValidationProfile.CUSTOM, selection)


def test_api_preserves_selected_checks():
    request = MigrationRequest(
        source={"type": "oracle", "host": "h", "service": "s", "username": "u", "password": "p"},
        target={"type": "azure_postgresql", "host": "h", "database": "d", "username": "u", "password": "p"},
        profile="custom", selected_checks=["row_count"],
    )
    assert request.to_migration_config().validation.selected_checks == ["row_count"]