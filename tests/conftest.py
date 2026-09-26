import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support import Seeds, push_all, template_settings

from vera.main import create_app

DATASET_DIR = Path(
    os.environ.get(
        "VERA_DATASET_DIR", Path(__file__).parents[1] / "magicpin-ai-challenge" / "dataset"
    )
)


@pytest.fixture(scope="session")
def seeds() -> Seeds:
    if not DATASET_DIR.exists():
        pytest.skip(f"dataset not found at {DATASET_DIR}; set VERA_DATASET_DIR")
    return Seeds(DATASET_DIR)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(template_settings())) as test_client:
        yield test_client


@pytest.fixture
def loaded_client(client: TestClient, seeds: Seeds) -> TestClient:
    push_all(client, seeds)
    return client
