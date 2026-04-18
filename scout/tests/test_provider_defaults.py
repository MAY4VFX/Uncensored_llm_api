from unittest.mock import Mock

from scout.db import get_default_provider, should_auto_deploy_runpod


class DummySettings:
    def __init__(self, default_provider: str):
        self.default_provider = default_provider


def test_should_auto_deploy_runpod_when_provider_is_runpod():
    session = Mock()
    session.query.return_value.filter.return_value.first.return_value = DummySettings("runpod")

    assert get_default_provider(session) == "runpod"
    assert should_auto_deploy_runpod(session, None) is True
    assert should_auto_deploy_runpod(session, "runpod") is True


def test_should_not_auto_deploy_runpod_when_provider_is_modal():
    session = Mock()
    session.query.return_value.filter.return_value.first.return_value = DummySettings("modal")

    assert get_default_provider(session) == "modal"
    assert should_auto_deploy_runpod(session, None) is False
    assert should_auto_deploy_runpod(session, "modal") is False
