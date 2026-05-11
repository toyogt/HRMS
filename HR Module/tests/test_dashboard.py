from pathlib import Path

from fastapi.testclient import TestClient

from attendance_relay.ingress_app import create_ingress_app
from attendance_relay.settings import Settings


def test_dashboard_renders_attendance_rows(tmp_path: Path) -> None:
    settings = Settings(
        env="test",
        db_url=f"sqlite:///{tmp_path / 'dash.db'}",
        log_level="WARNING",
        outbound_api_key="test-key",
    )
    app = create_ingress_app(settings)
    with TestClient(app) as client:
        payload = b"user_id=E1023\tio_time=20260501184510\tdev_id=SN-DASH-01\n"
        response = client.post("/machine/realtime_glog", headers={"request_code": "realtime_glog"}, content=payload)
        assert response.status_code == 200

        dash = client.get("/dashboard")
        assert dash.status_code == 200
        assert "Attendance Dashboard" in dash.text
        assert "E1023" in dash.text
        assert "SN-DASH-01" in dash.text

        data = client.get("/api/attendances")
        assert data.status_code == 200
        body = data.json()
        assert body["loaded"] >= 1
