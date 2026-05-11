from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


DEFAULT_CONFIG_PATH = Path("configs/dev.yaml")
ENV_PREFIX = "ATT_RELAY_"


class Settings(BaseModel):
    env: str = "dev"
    log_level: str = "INFO"
    tz_name: str = "Asia/Calcutta"

    ingress_host: str = "0.0.0.0"
    ingress_port: int = 9100
    ingress_path: str = "/machine/realtime_glog"
    expected_request_code: str = "realtime_glog"
    machine_ok_response_code: str = "OK"

    direct_listener_host: str = "0.0.0.0"
    direct_listener_port: int = 8010
    direct_listener_path: str = "/machine/realtime_glog"
    direct_listener_jsonl_path: str = "var/direct_listener/punches.jsonl"

    db_url: str = "sqlite:///attendance.db"
    db_pool_pre_ping: bool = True
    db_echo: bool = False

    outbox_batch_size: int = 100
    outbox_poll_seconds: float = 1.0
    processing_lease_seconds: int = 120
    stale_processing_seconds: int = 300
    max_retries: int = 5
    backoff_base_seconds: float = 1.5
    backoff_max_seconds: float = 60.0
    backoff_jitter_seconds: float = 0.75

    outbound_url: str = "https://localhost:9443/api/attendance"
    outbound_api_key_header: str = "x-api-key"
    outbound_api_key: str = "change-me"
    outbound_timeout_seconds: float = 15.0
    outbound_verify_tls: bool = True
    outbound_method: str = "POST"
    enforce_https: bool = True
    enforce_post: bool = True
    outbound_include_extended_fields: bool = True
    outbound_device_name_default: str = ""
    outbound_device_no_default: str = ""

    worker_health_file: str = "var/worker/health.json"
    worker_max_loop_errors: int = 100

    machine_sdk_dll_path: str = "sdk_extracted/20211204-SBXPC-1/bin/SBXPCDLL64.dll"
    machine_sync_ip: str = ""
    machine_sync_port: int = 5005
    machine_sync_password: int = 0
    machine_sync_machine_number: int = 1
    machine_sync_timezone1: int = 1
    machine_sync_timezone2: int = 0
    machine_sync_group_no: int = 1
    auto_register_device_from_ingress: bool = True

    middleware_api_key: str = "change-me-middleware"
    middleware_bearer_token: str = ""
    agent_api_key: str = "change-me-agent"
    agent_jwt_token: str = "change-me-agent-jwt"
    webhook_hmac_secret: str = "change-me-webhook-secret"
    webhook_timeout_seconds: float = 10.0
    webhook_dispatch_batch_size: int = 50
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["*"])

    @model_validator(mode="after")
    def _enforce_transport_policy(self) -> "Settings":
        if self.enforce_https and not self.outbound_url.lower().startswith("https://"):
            raise ValueError("outbound_url must start with https:// when enforce_https=true")
        if self.enforce_post and self.outbound_method.upper() != "POST":
            raise ValueError("outbound_method must be POST when enforce_post=true")
        if not self.outbound_api_key:
            raise ValueError("outbound_api_key cannot be empty")
        if not self.middleware_api_key:
            raise ValueError("middleware_api_key cannot be empty")
        if not self.middleware_bearer_token:
            self.middleware_bearer_token = self.middleware_api_key
        if not self.agent_api_key:
            raise ValueError("agent_api_key cannot be empty")
        if not self.webhook_hmac_secret:
            raise ValueError("webhook_hmac_secret cannot be empty")
        return self


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a top-level object: {path}")
    return data


def _env_overrides() -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for field in Settings.model_fields.keys():
        env_key = f"{ENV_PREFIX}{field.upper()}"
        if env_key in os.environ:
            overrides[field] = os.environ[env_key]
    return overrides


def load_settings(config_path: str | None = None) -> Settings:
    raw_path = config_path or os.getenv(f"{ENV_PREFIX}CONFIG") or str(DEFAULT_CONFIG_PATH)
    path = Path(raw_path)
    merged = _read_yaml(path)
    merged.update(_env_overrides())
    return Settings.model_validate(merged)
