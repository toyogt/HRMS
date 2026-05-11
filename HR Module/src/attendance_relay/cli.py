from __future__ import annotations

import argparse

import uvicorn

from attendance_relay.db import create_db_engine, init_local_schema, is_sqlite
from attendance_relay.direct_listener_app import create_direct_listener_app
from attendance_relay.ingress_app import create_ingress_app
from attendance_relay.middleware_repository import MiddlewareRepository
from attendance_relay.outbound_client import OutboundClient
from attendance_relay.repository import AttendanceRepository
from attendance_relay.settings import load_settings
from attendance_relay.webhook_dispatcher import dispatch_due_webhooks
from attendance_relay.worker import RelayWorker


def run_ingress() -> None:
    parser = argparse.ArgumentParser(description="Run realtime ingestion API.")
    parser.add_argument("--config", default=None, help="Path to YAML config.")
    args = parser.parse_args()
    settings = load_settings(args.config)
    app = create_ingress_app(settings)
    uvicorn.run(app, host=settings.ingress_host, port=settings.ingress_port)


def run_gateway() -> None:
    parser = argparse.ArgumentParser(description="Run HRMS middleware gateway API (ingress + machine control).")
    parser.add_argument("--config", default=None, help="Path to YAML config.")
    args = parser.parse_args()
    settings = load_settings(args.config)
    app = create_ingress_app(settings)
    uvicorn.run(app, host=settings.ingress_host, port=settings.ingress_port)


def run_webhook_dispatch() -> None:
    parser = argparse.ArgumentParser(description="Dispatch due middleware webhooks once.")
    parser.add_argument("--config", default=None, help="Path to YAML config.")
    parser.add_argument("--limit", type=int, default=None, help="Max deliveries to dispatch.")
    args = parser.parse_args()

    settings = load_settings(args.config)
    engine = create_db_engine(settings)
    if is_sqlite(engine):
        init_local_schema(engine)
    repo = MiddlewareRepository(engine)
    limit = args.limit if args.limit is not None else settings.webhook_dispatch_batch_size
    result = dispatch_due_webhooks(settings=settings, repo=repo, limit=limit)
    print(result)
    engine.dispose()


def run_direct_listener() -> None:
    parser = argparse.ArgumentParser(description="Run direct machine listener API.")
    parser.add_argument("--config", default=None, help="Path to YAML config.")
    args = parser.parse_args()
    settings = load_settings(args.config)
    app = create_direct_listener_app(settings)
    uvicorn.run(app, host=settings.direct_listener_host, port=settings.direct_listener_port)


def run_worker() -> None:
    parser = argparse.ArgumentParser(description="Run outbox relay worker.")
    parser.add_argument("--config", default=None, help="Path to YAML config.")
    args = parser.parse_args()
    settings = load_settings(args.config)

    engine = create_db_engine(settings)
    if is_sqlite(engine):
        init_local_schema(engine)

    repo = AttendanceRepository(engine)
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
    worker = RelayWorker(settings=settings, repo=repo, outbound=outbound)
    worker.run_forever()
