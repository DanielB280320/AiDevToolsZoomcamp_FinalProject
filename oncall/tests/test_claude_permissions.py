"""The generated allow-list against the real `claude` CLI's permission evaluation.

Drill S1 attempt 2: the allow-list had `Write(//<inc>/issue.md)` and the agent's Write of issue.md
was refused in dontAsk mode. A string-level test cannot see that, so this one starts the real CLI
(`claude -p`, same flags and settings file as the responder, without the guard hook so only the
permission rules decide) against a local fake of the Anthropic messages API that answers with one
scripted tool call and records the tool result. No network, no credentials. Skipped when `claude`
is not installed (CI); run it locally and on the host after upgrading Claude Code.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from collections.abc import Iterator
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from responder.agent import _env, build_settings, command_line
from responder.config import Settings
from responder.store import Incident

pytestmark = pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not installed")


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


class FakeAnthropic:
    """Answers every request with the scripted tool call, then with text once a result is back."""

    def __init__(self) -> None:
        self.tool: dict[str, Any] = {}
        self.tool_in: dict[str, Any] = {}
        self.results: list[dict[str, Any]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("content-length", 0))
                req = json.loads(self.rfile.read(length) or b"{}")
                results = [
                    block
                    for msg in req.get("messages", [])
                    if isinstance(msg.get("content"), list)
                    for block in msg["content"]
                    if isinstance(block, dict) and block.get("type") == "tool_result"
                ]
                if results:
                    fake.results = results
                    block: dict[str, Any] = {"type": "text", "text": ""}
                    delta: dict[str, Any] = {"type": "text_delta", "text": "done"}
                    stop = "end_turn"
                else:
                    block = {**fake.tool, "type": "tool_use", "id": "toolu_1", "input": {}}
                    delta = {"type": "input_json_delta", "partial_json": json.dumps(fake.tool_in)}
                    stop = "tool_use"
                body = _sse(
                    "message_start",
                    {
                        "type": "message_start",
                        "message": {
                            "id": "m",
                            "type": "message",
                            "role": "assistant",
                            "model": req.get("model", "m"),
                            "content": [],
                            "stop_reason": None,
                            "usage": {"input_tokens": 1, "output_tokens": 1},
                        },
                    },
                )
                body += _sse(
                    "content_block_start",
                    {"type": "content_block_start", "index": 0, "content_block": block},
                )
                body += _sse(
                    "content_block_delta",
                    {"type": "content_block_delta", "index": 0, "delta": delta},
                )
                body += _sse("content_block_stop", {"type": "content_block_stop", "index": 0})
                body += _sse(
                    "message_delta",
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": stop},
                        "usage": {"output_tokens": 1},
                    },
                )
                body += _sse("message_stop", {"type": "message_stop"})
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                self.wfile.write(body.encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"


@pytest.fixture(scope="module")
def fake() -> Iterator[FakeAnthropic]:
    server = FakeAnthropic()
    yield server
    server.server.shutdown()


@pytest.fixture
def real(settings: Settings, tmp_path: Path) -> tuple[Settings, Incident]:
    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / "oncall").mkdir()
    path = tmp_path / "incidents" / "20261103T051920Z-c9616e4f3c53"
    path.mkdir(parents=True)
    st = replace(
        settings,
        agent_enabled=True,
        clone_dir=clone,
        agent_home=tmp_path / "home",
        repo_dir=tmp_path,
    )
    st.agent_home.mkdir()
    return st, Incident(id=path.name, path=path)


def _run(
    fake: FakeAnthropic, real: tuple[Settings, Incident], name: str, tool_in: dict[str, Any]
) -> str:
    import subprocess

    st, inc = real
    cfg = build_settings(st, inc)
    cfg.pop("hooks")  # the guard has its own tests; here only the permission rules decide
    (inc.path / "agent-settings.json").write_text(json.dumps(cfg))
    env = _env(st, inc)
    env.update(
        ANTHROPIC_BASE_URL=fake.url,
        ANTHROPIC_API_KEY="sk-ant-fake",
        PATH=os.environ["PATH"],
        DISABLE_TELEMETRY="1",
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
    )
    env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    fake.tool, fake.tool_in, fake.results = {"name": name}, tool_in, []
    subprocess.run(
        command_line(st, inc),
        input="go",
        capture_output=True,
        text=True,
        env=env,
        cwd=st.repo_dir,
        timeout=120,
        check=False,
    )
    assert fake.results, "the CLI never reported a tool result"
    return str(fake.results[0].get("content"))


def _allowed(result: str) -> bool:
    return "denied" not in result and "Permission" not in result


@pytest.mark.parametrize("tool", ["Write", "Edit"])
@pytest.mark.parametrize("name", ["issue.md", "pr.md", "commit-msg.txt"])
def test_incident_draft_files_can_be_written(
    fake: FakeAnthropic, real: tuple[Settings, Incident], tool: str, name: str
):
    target = real[1].path / name
    tool_in = (
        {"file_path": str(target), "content": "x"}
        if tool == "Write"
        else {"file_path": str(target), "old_string": "a", "new_string": "b"}
    )
    if tool == "Edit":
        target.write_text("a")
    result = _run(fake, real, tool, tool_in)
    assert _allowed(result), result
    if tool == "Write":
        assert target.read_text() == "x"


def test_other_files_in_the_incident_folder_are_refused(
    fake: FakeAnthropic, real: tuple[Settings, Incident]
):
    target = real[1].path / "notes.md"
    result = _run(fake, real, "Write", {"file_path": str(target), "content": "x"})
    assert not _allowed(result) and not target.exists()


def test_clone_is_writable_but_protected_parts_and_outside_are_not(
    fake: FakeAnthropic, real: tuple[Settings, Incident], tmp_path: Path
):
    st, _ = real
    ok = st.clone_dir / "backend.py"
    assert _allowed(_run(fake, real, "Write", {"file_path": str(ok), "content": "x"}))
    assert ok.exists()
    for bad in (st.clone_dir / "oncall" / "x.py", tmp_path / "outside.txt"):
        result = _run(fake, real, "Write", {"file_path": str(bad), "content": "x"})
        assert not _allowed(result), bad
        assert not bad.exists()
