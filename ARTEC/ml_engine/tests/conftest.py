import pytest
from ml_engine.schemas import EngineConfig
from ml_engine.synthetic import generate_synthetic


@pytest.fixture(scope="session")
def synth():
    return generate_synthetic()  # (df, truth) -- DONNÉES FICTIVES


@pytest.fixture
def cfg():
    return EngineConfig(reference_now="2026-10-25T00:00:00+00:00", use_registry_models=False)
