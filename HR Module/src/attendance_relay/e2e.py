from __future__ import annotations

import argparse
import json
import ssl
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient

from attendance_relay.ingress_app import create_ingress_app
from attendance_relay.outbound_client import OutboundClient
from attendance_relay.settings import Settings
from attendance_relay.worker import RelayWorker
import trustme


@dataclass
class ReceiverState:
    records: list[dict[str, Any]] = field(default_factory=list)
    api_key_header: str = "x-api-key"
    api_key_value: str = "e2e-secret"


class CaptureHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        payload = json.loads(body.decode("utf-8"))

        state: ReceiverState = self.server.state  # type: ignore[attr-defined]
        record = {
            "path": self.path,
            "payload": payload,
            "api_key_match": self.headers.get(state.api_key_header) == state.api_key_value,
        }
        state.records.append(record)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local end-to-end relay test.")
    parser.add_argument("--events", type=int, default=10, help="Number of simulated events.")
    parser.add_argument("--duplicates", type=int, default=2, help="Number of duplicate posts to include.")
    args = parser.parse_args()

    with TemporaryDirectory(prefix="attendance_e2e_") as tmp_dir:
        tmp = Path(tmp_dir)
        cert_file = tmp / "server.crt"
        key_file = tmp / "server.key"
        _generate_tls_material(cert_file, key_file)

        receiver_state = ReceiverState()
        receiver, thread, receiver_url = _start_https_receiver(
            cert_file=cert_file,
            key_file=key_file,
            state=receiver_state,
        )
        try:
            settings = Settings(
                env="e2e",
                log_level="WARNING",
                db_url=f"sqlite:///{tmp / 'attendance.db'}",
                outbound_url=f"{receiver_url}/api/attendance",
                outbound_api_key=receiver_state.api_key_value,
                outbound_api_key_header=receiver_state.api_key_header,
                outbound_verify_tls=False,
                outbox_batch_size=100,
                outbox_poll_seconds=0.1,
                max_retries=5,
                enforce_https=True,
                enforce_post=True,
            )

            app = create_ingress_app(settings)

            with TestClient(app) as client:
                sent = _simulate_machine_posts(client=client, count=args.events, duplicates=args.duplicates)
                outbound = OutboundClient(
                    url=settings.outbound_url,
                    api_key_header=settings.outbound_api_key_header,
                    api_key=settings.outbound_api_key,
                    timeout_seconds=settings.outbound_timeout_seconds,
                    verify_tls=settings.outbound_verify_tls,
                    enforce_https=settings.enforce_https,
                    enforce_post=settings.enforce_post,
                    method=settings.outbound_method,
                )
                worker = RelayWorker(settings=settings, repo=app.state.repo, outbound=outbound)
                while worker.run_once() > 0:
                    pass

                counts = app.state.repo.get_outbox_counts()
                expected_non_duplicates = args.events - max(min(args.duplicates, args.events), 0)
                passed = (
                    counts.get("SENT", 0) == expected_non_duplicates
                    and counts.get("PENDING", 0) == 0
                    and counts.get("PROCESSING", 0) == 0
                )
                report = {
                    "sent_to_ingress": sent,
                    "receiver_records": len(receiver_state.records),
                    "outbox_counts": counts,
                    "expected_non_duplicates": expected_non_duplicates,
                    "passed": passed,
                }
                print(json.dumps(report, indent=2))
                app.state.engine.dispose()
        finally:
            receiver.shutdown()
            thread.join(timeout=3)


def _generate_tls_material(cert_file: Path, key_file: Path) -> None:
    ca = trustme.CA()
    cert = ca.issue_cert("localhost", "127.0.0.1")
    cert.cert_chain_pems[0].write_to_path(cert_file)
    cert.private_key_pem.write_to_path(key_file)


def _start_https_receiver(*, cert_file: Path, key_file: Path, state: ReceiverState) -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), CaptureHandler)
    server.state = state  # type: ignore[attr-defined]

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
    server.socket = ctx.wrap_socket(server.socket, server_side=True)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, f"https://{host}:{port}"


def _simulate_machine_posts(*, client: TestClient, count: int, duplicates: int) -> int:
    sent = 0
    duplicate_count = max(min(duplicates, count), 0)
    unique_count = count - duplicate_count
    duplicate_employee = "E1000"
    duplicate_io_time = "20260501100000"

    for i in range(count):
        if i < unique_count:
            employee = f"E{1000 + i}"
            io_time = f"20260501{(10 + (i // 3600)) % 24:02d}{(i // 60) % 60:02d}{i % 60:02d}"
        else:
            employee = duplicate_employee
            io_time = duplicate_io_time

        payload = f"user_id={employee}\tio_time={io_time}\tdev_id=SN-E2E-01\n".encode("ascii")
        response = client.post(
            "/machine/realtime_glog",
            headers={"request_code": "realtime_glog"},
            content=payload,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Ingestion failed for event {i}: {response.status_code} {response.text}")
        sent += 1
    return sent
