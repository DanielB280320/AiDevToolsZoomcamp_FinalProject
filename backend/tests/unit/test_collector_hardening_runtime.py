"""Prod collector against an OTLP sender that applies none of dev's gates (#130, rule 6).

Runs the real collector image with `observability/collector/config.yaml`, exporters swapped for
file exporters, and posts hostile OTLP/HTTP JSON. Skipped when Docker or the pinned image is
not available locally. Uses an ephemeral host port and a unique container name, so it is safe
next to other stacks.
"""

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "observability" / "collector" / "config.yaml"
IMAGE = "otel/opentelemetry-collector-contrib:0.161.0"
EMAIL = "victim@example.com"


def _docker(*args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _image_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return _docker("image", "inspect", IMAGE).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


pytestmark = pytest.mark.skipif(not _image_available(), reason="docker / collector image missing")


def _file_config(out: str) -> dict[str, Any]:
    cfg: dict[str, Any] = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    cfg["exporters"] = {
        f"file/{signal}": {"path": f"{out}/{signal}.json", "flush_interval": "200ms"}
        for signal in ("traces", "metrics", "logs")
    }
    pipelines = cfg["service"]["pipelines"]
    pipelines["traces"]["exporters"] = ["file/traces"]
    pipelines["metrics"]["exporters"] = ["file/metrics"]
    pipelines["logs/forwarded"]["exporters"] = ["file/logs"]
    # The Docker fluentd source is irrelevant here.
    del pipelines["logs"]
    del cfg["receivers"]["fluent_forward"]
    cfg["processors"]["batch"]["timeout"] = "200ms"
    return cfg


@pytest.fixture(scope="module")
def collector(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, Path]]:
    work = tmp_path_factory.mktemp("collector")
    out = work / "out"
    out.mkdir()
    out.chmod(0o777)
    (work / "config.yaml").write_text(yaml.safe_dump(_file_config("/out")), encoding="utf-8")
    name = f"fitwise-collector-test-{uuid.uuid4().hex[:8]}"
    run = _docker(
        "run", "-d", "--rm", "--name", name,
        "-e", "FITWISE_ENV=prod",
        "-p", "127.0.0.1::4318",
        "-v", f"{work}/config.yaml:/etc/otelcol/config.yaml:ro",
        "-v", f"{out}:/out",
        IMAGE, "--config=/etc/otelcol/config.yaml",
    )  # fmt: skip
    assert run.returncode == 0, run.stderr
    try:
        port = _docker("port", name, "4318/tcp").stdout.split("\n")[0].split(":")[-1].strip()
        url = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                urllib.request.urlopen(f"{url}/", timeout=1)  # noqa: S310
            except urllib.error.HTTPError:
                break  # any HTTP answer: the receiver is listening
            except OSError:
                time.sleep(0.5)
        yield url, out
    finally:
        _docker("rm", "-f", name)


def _post(url: str, path: str, body: dict[str, Any]) -> None:
    req = urllib.request.Request(  # noqa: S310
        f"{url}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert urllib.request.urlopen(req, timeout=5).status == 200  # noqa: S310


def _read(out: Path, signal: str, wait_for: str) -> str:
    path = out / f"{signal}.json"
    for _ in range(50):
        if path.exists() and wait_for in path.read_text(encoding="utf-8"):
            break
        time.sleep(0.2)
    time.sleep(0.5)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _attrs(**values: str) -> list[dict[str, Any]]:
    return [{"key": k, "value": {"stringValue": v}} for k, v in values.items()]


def test_map_body_with_email_never_reaches_the_exporter(collector: tuple[str, Path]) -> None:
    url, out = collector
    map_body = {"kvlistValue": {"values": [{"key": "msg", "value": {"stringValue": EMAIL}}]}}
    records = [
        {"body": map_body, "attributes": _attrs(route="/map-body")},
        {
            "body": {"stringValue": f"login {EMAIL} Bearer abc.def"},
            "attributes": _attrs(route="/str"),
        },
    ]
    _post(
        url,
        "/v1/logs",
        {
            "resourceLogs": [
                {
                    "resource": {"attributes": _attrs(**{"service.name": "fitwise-backend"})},
                    "scopeLogs": [{"logRecords": records}],
                }
            ]
        },
    )
    text = _read(out, "logs", "/str")
    assert "/map-body" in text, "the record itself is kept (allowed attribute), body blanked"
    assert EMAIL not in text
    assert "[email]" in text
    assert "abc.def" not in text


def test_records_without_body_or_allowed_attributes_are_dropped(
    collector: tuple[str, Path],
) -> None:
    url, out = collector
    records = [
        {"body": {"stringValue": ""}, "attributes": _attrs(note="DROPPED-EMPTY-1")},
        {"body": {"kvlistValue": {"values": []}}, "attributes": _attrs(secret="DROPPED-EMPTY-2")},
        {"body": {"stringValue": "kept body"}, "attributes": _attrs(secret="DROPPED-ATTR")},
    ]
    _post(url, "/v1/logs", {"resourceLogs": [{"scopeLogs": [{"logRecords": records}]}]})
    text = _read(out, "logs", "kept body")
    assert "kept body" in text
    assert "DROPPED" not in text
    lines = [json.loads(line) for line in text.splitlines() if "kept body" in line]
    exported = [
        rec
        for line in lines
        for rl in line["resourceLogs"]
        for sl in rl["scopeLogs"]
        for rec in sl["logRecords"]
    ]
    assert [r["body"]["stringValue"] for r in exported] == ["kept body"]


def test_resource_and_scope_attributes_are_allow_listed(collector: tuple[str, Path]) -> None:
    url, out = collector
    resource = {
        "attributes": _attrs(
            **{
                "service.name": "fitwise-backend",
                "env": "dev",
                "host.name": "HOSTNAME-LEAK",
                "user.email": EMAIL,
            }
        )
    }
    scope = {"name": "s", "attributes": _attrs(note="SCOPE-LEAK")}
    log = {"body": {"stringValue": "res-log"}}
    span = {
        "traceId": "0123456789abcdef0123456789abcdef",
        "spanId": "0123456789abcdef",
        "name": "res-span",
        "attributes": _attrs(user_hash="u1"),
    }
    logs_body = {
        "resourceLogs": [
            {"resource": resource, "scopeLogs": [{"scope": scope, "logRecords": [log]}]}
        ]
    }
    spans_body = {
        "resourceSpans": [{"resource": resource, "scopeSpans": [{"scope": scope, "spans": [span]}]}]
    }
    _post(url, "/v1/logs", logs_body)
    _post(url, "/v1/traces", spans_body)
    logs = _read(out, "logs", "res-log")
    traces = _read(out, "traces", "res-span")
    for text in (logs, traces):
        assert "HOSTNAME-LEAK" not in text
        assert EMAIL not in text
        assert "SCOPE-LEAK" not in text
        assert '"fitwise-backend"' in text
        assert '"dev"' in text, "the sender's env is kept, not overwritten with prod"
