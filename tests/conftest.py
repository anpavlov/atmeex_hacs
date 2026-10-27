import os

import pytest

import custom_components

# The plugin brings its own custom_components package from testing_config
custom_components.__path__.append(os.path.join(os.path.dirname(__file__), "..", "custom_components"))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
