from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health():
    """
    Test the liveness check /health endpoint to ensure routing, settings,
    and middleware are correctly initialized.
    """
    response = client.get("/erp/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "erp" in data
    assert "version" in data
    assert "timestamp" in data
