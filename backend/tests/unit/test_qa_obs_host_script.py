"""QA (#67): deploy/obs.sh on a simulated host, with stub `docker` and `curl` on PATH.

Checks the properties the issue relies on: best effort (never a non-zero exit for telemetry
problems), idempotent (containers recreated only when observability/ changed), only public
GitHub downloads without credentials, the right services per mode, and no secret in the output.
No network and no Docker: both commands are stubs that record their arguments.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
OBS_SH = REPO_ROOT / "deploy" / "obs.sh"
SHA = "a" * 40
SECRET = "s3cr3t-grafana-value"
BASH = shutil.which("bash") or "/bin/bash"

CURL_STUB = """#!/usr/bin/env bash
out=""; url=""; prev=""
for a in "$@"; do
  case "$a" in https://*) url="$a";; esac
  [ "$prev" = "-o" ] && out="$a"
  prev="$a"
done
printf 'curl %s\\n' "$*" >> "$STUB_LOG"
case "$url" in
  *codeload.github.com*) [ -z "${CURL_FAIL_CODELOAD:-}" ] || exit 22; cat "$STUB_TARBALL";;
  *) [ -n "$out" ] && echo "# stub" > "$out";;
esac
"""

DOCKER_STUB = """#!/usr/bin/env bash
printf 'docker %s\\n' "$*" >> "$STUB_LOG"
exit "${DOCKER_RC:-0}"
"""


def _tarball(path: Path, content: str) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in ("observability/collector/config.yaml", "README.md"):
            data = content.encode()
            info = tarfile.TarInfo(f"repo-{SHA}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    path.write_bytes(buf.getvalue())


@pytest.fixture
def host(tmp_path: Path) -> dict[str, Path]:
    app = tmp_path / "app"
    rel = app / "releases" / SHA
    rel.mkdir(parents=True)
    (rel / "release.env").write_text("BACKEND_IMAGE=x\nFRONTEND_IMAGE=y\n")
    (app / "CURRENT_TAG").write_text(SHA + "\n")
    stub = tmp_path / "stub"
    stub.mkdir()
    for name, body in (("curl", CURL_STUB), ("docker", DOCKER_STUB)):
        (stub / name).write_text(body)
        (stub / name).chmod(0o755)
    tarball = tmp_path / "obs.tgz"
    _tarball(tarball, "v1")
    return {"app": app, "stub": stub, "tarball": tarball, "log": tmp_path / "calls.log"}


def _env_file(host: dict[str, Path], text: str) -> None:
    (host["app"] / ".env").write_text(text)


def _run(host: dict[str, Path], **extra: str) -> subprocess.CompletedProcess[str]:
    host["log"].write_text("")
    env = {
        "PATH": f"{host['stub']}:{os.environ['PATH']}",
        "APP_DIR": str(host["app"]),
        "GITHUB_REPOSITORY": "owner/repo",
        "FITWISE_LOCKED": "1",
        "LOCK_FILE": str(host["app"] / "lock"),
        "STUB_LOG": str(host["log"]),
        "STUB_TARBALL": str(host["tarball"]),
        **extra,
    }
    return subprocess.run(
        [BASH, str(OBS_SH), SHA], env=env, capture_output=True, text=True, timeout=60
    )


def _up_calls(host: dict[str, Path]) -> list[str]:
    return [
        line
        for line in host["log"].read_text().splitlines()
        if line.startswith("docker") and " up " in line
    ]


FULL = f"OBS_MODE=full\nGRAFANA_ADMIN_PASSWORD={SECRET}\n"
FORWARD = (
    f"OBS_MODE=forward\nGRAFANA_ADMIN_PASSWORD={SECRET}\nOTLP_UPSTREAM_ENDPOINT=10.0.0.1:4317\n"
)


def test_full_mode_first_run_recreates_and_reports_ok(host: dict[str, Path]) -> None:
    _env_file(host, FULL)
    res = _run(host)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "obs: OK (full)" in res.stdout
    [up] = _up_calls(host)
    assert "--force-recreate" in up
    assert "-f compose.observability.yaml -f compose.obs-full.yaml" in up
    for svc in ("otel-collector", "prometheus", "loki", "tempo", "grafana", "obs-probe"):
        assert svc in up.split()
    assert (host["app"] / "observability" / "collector" / "config.yaml").read_text() == "v1"
    assert (host["app"] / "OBS_CONFIG_HASH").read_text().strip()


def test_unchanged_config_is_not_recreated_changed_config_is(host: dict[str, Path]) -> None:
    _env_file(host, FULL)
    _run(host)
    res = _run(host)
    assert res.returncode == 0
    [up] = _up_calls(host)
    assert "--force-recreate" not in up
    _tarball(host["tarball"], "v2")
    _run(host)
    [up] = _up_calls(host)
    assert "--force-recreate" in up
    assert (host["app"] / "observability" / "collector" / "config.yaml").read_text() == "v2"


def test_forward_mode_starts_only_the_collector(host: dict[str, Path]) -> None:
    _env_file(host, FORWARD)
    res = _run(host)
    assert res.returncode == 0
    assert "obs: OK (forward)" in res.stdout
    [up] = _up_calls(host)
    assert "-f compose.obs-forward.yaml" in up
    assert up.split()[-1] == "otel-collector"
    for svc in ("prometheus", "loki", "tempo", "grafana"):
        assert svc not in up.split()


def test_unhealthy_stack_is_a_warning_and_forgets_the_hash(host: dict[str, Path]) -> None:
    _env_file(host, FULL)
    res = _run(host, DOCKER_RC="1")
    assert res.returncode == 0
    assert "obs: WARNING" in res.stdout
    assert not (host["app"] / "OBS_CONFIG_HASH").exists()


def test_download_failure_keeps_running_config(host: dict[str, Path]) -> None:
    _env_file(host, FULL)
    _run(host)
    res = _run(host, CURL_FAIL_CODELOAD="1")
    assert res.returncode == 0
    assert "cannot download" in res.stdout
    assert _up_calls(host) == []
    assert (host["app"] / "observability" / "collector" / "config.yaml").read_text() == "v1"


@pytest.mark.parametrize(
    "env_text",
    ["APP_ENV=prod\n", "OBS_MODE=full\n", "OBS_MODE=forward\nGRAFANA_ADMIN_PASSWORD=x\n"],
)
def test_off_or_incomplete_does_nothing(host: dict[str, Path], env_text: str) -> None:
    _env_file(host, env_text)
    res = _run(host)
    assert res.returncode == 0
    assert host["log"].read_text() == ""


def test_downloads_only_public_github_without_credentials_and_prints_no_secret(
    host: dict[str, Path],
) -> None:
    _env_file(host, FULL)
    res = _run(host)
    curls = [line for line in host["log"].read_text().splitlines() if line.startswith("curl")]
    assert curls
    for line in curls:
        urls = [w for w in line.split() if w.startswith("http")]
        assert urls and all(
            u.startswith(
                (
                    "https://raw.githubusercontent.com/owner/repo/",
                    "https://codeload.github.com/owner/repo/",
                )
            )
            for u in urls
        ), line
        assert "Authorization" not in line and "token" not in line.lower()
    assert SECRET not in res.stdout + res.stderr
