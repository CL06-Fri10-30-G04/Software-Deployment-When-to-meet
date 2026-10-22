import os

import httpx
import pytest

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")


@pytest.mark.skipif(
    not os.getenv("BASE_URL"), reason="requires a running application container"
)
def test_app_health_via_base_url():
    response = httpx.get(f"{BASE_URL}/api/health", timeout=10.0)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
