from unittest.mock import Mock, patch

from src.app.admin.initialize import create_admin_interface
from src.app.platform.config import load_settings


def test_create_admin_interface_returns_none_when_admin_feature_toggle_is_disabled() -> None:
    custom_settings = load_settings(
        _env_file=None,
        FEATURE_ADMIN_ENABLED=False,
        CRUD_ADMIN_ENABLED=True,
    )

    with (
        patch("src.app.admin.initialize.settings", custom_settings),
        patch("src.app.admin.initialize.CRUDAdmin") as crud_admin_mock,
    ):
        admin = create_admin_interface()

    assert admin is None
    crud_admin_mock.assert_not_called()


def test_create_admin_interface_still_builds_admin_when_feature_toggle_is_enabled() -> None:
    custom_settings = load_settings(
        _env_file=None,
        FEATURE_ADMIN_ENABLED=True,
        CRUD_ADMIN_ENABLED=True,
    )
    admin_instance = Mock()

    with (
        patch("src.app.admin.initialize.settings", custom_settings),
        patch("src.app.admin.initialize.CRUDAdmin", return_value=admin_instance) as crud_admin_mock,
        patch("src.app.admin.initialize.register_admin_views") as register_admin_views,
    ):
        admin = create_admin_interface()

    assert admin is admin_instance
    crud_admin_mock.assert_called_once()
    register_admin_views.assert_called_once_with(admin_instance)
