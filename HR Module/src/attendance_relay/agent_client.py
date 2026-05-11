from __future__ import annotations

import argparse
import os
from typing import Any

import httpx


def _parse_device_ids(raw: str) -> list[str]:
    return [v.strip() for v in (raw or "").split(",") if v.strip()]


def _headers(api_key: str, jwt_token: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json",
    }


def run_once(args: argparse.Namespace) -> int:
    base_url = args.base_url.rstrip("/")
    api_key = args.api_key or os.getenv("ATT_RELAY_AGENT_API_KEY", "")
    jwt_token = args.jwt_token or os.getenv("ATT_RELAY_AGENT_JWT_TOKEN", "")
    if not api_key or not jwt_token:
        print("agent api key and jwt token are required")
        return 2

    device_ids = _parse_device_ids(args.device_ids)
    headers = _headers(api_key, jwt_token)
    timeout = float(args.timeout_seconds)

    with httpx.Client(timeout=timeout, verify=args.verify_tls) as client:
        hb = client.post(
            f"{base_url}/api/v1/agent/heartbeat",
            headers=headers,
            json={
                "agent_id": args.agent_id,
                "site_id": args.site_id,
                "version": args.version,
                "host_name": args.host_name,
                "local_ip": args.local_ip,
                "details": {"mode": "mock" if args.mock_execute else "dry"},
            },
        )
        print(f"heartbeat status={hb.status_code}")
        if hb.status_code >= 300:
            print(hb.text[:1000])
            return 1

        claim = client.post(
            f"{base_url}/api/v1/agent/commands/claim",
            headers=headers,
            json={
                "agent_id": args.agent_id,
                "device_ids": device_ids,
                "limit": args.claim_limit,
            },
        )
        print(f"claim status={claim.status_code}")
        if claim.status_code >= 300:
            print(claim.text[:1000])
            return 1

        rows = claim.json().get("rows", [])
        print(f"claimed_commands={len(rows)}")
        if not args.mock_execute:
            for row in rows:
                print(f"dry-claimed command_id={row.get('command_id')} type={row.get('command_type')}")
            return 0

        for row in rows:
            command_id = str(row.get("command_id") or "").strip()
            if not command_id:
                continue
            result = client.post(
                f"{base_url}/api/v1/agent/commands/{command_id}/result",
                headers=headers,
                json={
                    "agent_id": args.agent_id,
                    "success": True,
                    "result_payload": {
                        "mock_executed": True,
                        "command_type": row.get("command_type"),
                        "device_id": row.get("device_id"),
                    },
                },
            )
            print(f"result command_id={command_id} status={result.status_code}")
            if result.status_code >= 300:
                print(result.text[:1000])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local agent mock client for HRMS middleware testing.")
    parser.add_argument("--base-url", default="http://127.0.0.1:9100", help="Middleware base URL.")
    parser.add_argument("--agent-id", default="AGENT_LOCAL_01", help="Agent identifier.")
    parser.add_argument("--site-id", default="", help="Site identifier.")
    parser.add_argument("--device-ids", default="", help="Comma-separated device IDs.")
    parser.add_argument("--version", default="1.0.0", help="Agent version.")
    parser.add_argument("--host-name", default="", help="Host name.")
    parser.add_argument("--local-ip", default="", help="Local IP.")
    parser.add_argument("--api-key", default="", help="Agent API key.")
    parser.add_argument("--jwt-token", default="", help="Agent JWT token.")
    parser.add_argument("--claim-limit", type=int, default=10, help="Command claim limit.")
    parser.add_argument("--timeout-seconds", type=float, default=10.0, help="HTTP timeout seconds.")
    parser.add_argument("--verify-tls", action="store_true", help="Enable TLS verification.")
    parser.add_argument("--mock-execute", action="store_true", help="Auto-submit successful command results.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(run_once(args))


if __name__ == "__main__":
    main()
