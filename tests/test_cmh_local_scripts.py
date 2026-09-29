"""bench.ps1 and start.ps1 run under the PowerShell this machine really has (5.1).

The audit of 2026-09-29 found that bench.ps1 aborted on its first call to lms.exe
under Windows PowerShell 5.1 - the only PowerShell installed - because
``2>&1`` over a native command with ErrorActionPreference=Stop turns the first
line of stderr into a terminating error. Nothing had ever run it: step 3.4 was
declared "scripts ready" on a script that could not start. It also did not
measure time to first token, its "3 rounds" were three identical single-turn
requests (the tool was never executed and its result never returned), it would
have measured all nine LLMs on disk, and its ``lms unload --all`` would have
unloaded whatever model the user had loaded without asking.

These tests run the real scripts with ``powershell.exe`` against a FAKE lms (a
Python script behind a .cmd, writing its progress to stderr like the real one)
and a FAKE OpenAI-compatible server that streams SSE, so nothing touches the
user's LM Studio and nothing is loaded or unloaded on the machine.
"""

import json
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

POWERSHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(not (sys.platform == "win32" and POWERSHELL),
                                reason="needs Windows PowerShell 5.1")

REPO = Path(__file__).resolve().parents[1]
BENCH = REPO / "scripts" / "cmh_local" / "bench.ps1"
START = REPO / "scripts" / "cmh_local" / "start.ps1"

FAKE_LMS = r'''
import json, sys
from pathlib import Path

state_dir = Path(__file__).resolve().parent / "state"
state = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
args = sys.argv[1:]
with (state_dir / "calls.log").open("a", encoding="utf-8") as log:
    log.write(" ".join(args) + "\n")


def save():
    (state_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")


if args[0] == "ls":
    print(state["ls"])
elif args[0] == "ps":
    loaded = state["loaded"]
    if not loaded:
        print("No models are currently loaded.")
    else:
        print("")
        print("IDENTIFIER          MODEL               STATUS    SIZE        CONTEXT    PARALLEL    DEVICE    TTL")
        for item in loaded:
            print(f"{item['identifier']:<19} {item['model']:<19} IDLE      6.33 GB     16384      4           Local")
elif args[0] == "load":
    if "--estimate-only" in args:
        print("Estimated Total Memory: 5.89 GiB", file=sys.stderr)
    else:
        identifier = args[args.index("--identifier") + 1] if "--identifier" in args else args[1]
        print("Loading model...", file=sys.stderr)
        state["loaded"].append({"identifier": identifier, "model": args[1]})
        save()
elif args[0] == "unload":
    print("Unloaded.", file=sys.stderr)
    if len(args) > 1 and args[1] == "--all":
        state["loaded"] = []
    elif len(args) > 1:
        state["loaded"] = [m for m in state["loaded"] if m["identifier"] != args[1]]
    save()
sys.exit(0)
'''

LS_TEXT = "\n".join([
    "You have 5 models, taking up 40.00 GB of disk space.",
    "",
    "LLM                                               PARAMS     ARCH        SIZE        DEVICE",
    "deepseek/deepseek-r1-0528-qwen3-8b (1 variant)    8B         qwen3       5.03 GB     Local",
    "google/gemma-4-e4b (1 variant)                    7.5B       gemma4      6.33 GB     Local",
    "openai/gpt-oss-20b (1 variant)                    20B        gpt-oss     12.11 GB    Local",
    "qwen/qwen3.8-27b (1 variant)                      27B        qwen35      17.74 GB    Local",
    "",
    "EMBEDDING                               PARAMS    ARCH          SIZE        DEVICE",
    "text-embedding-nomic-embed-text-v1.5              Nomic BERT    84.11 MB    Local",
])

# Tuned so that generation seconds and total seconds differ enough to tell them apart
# through scheduling jitter: 0.6 s before the first token, 0.1 s of streaming after.
FIRST_TOKEN_DELAY = 0.6
STREAM_TIME = 0.1
TOKENS_PER_ROUND = 40


class FakeServer:
    """A stand-in for LM Studio's OpenAI-compatible API, streaming SSE."""

    def __init__(self):
        self.mode = "good"
        self.requests = []
        self.up = True
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"data": []}')

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                tool_messages = [m for m in body["messages"] if m.get("role") == "tool"]
                chunks = outer.plan(len(tool_messages))
                # Nothing on the wire until the "prompt evaluation" is over, then the
                # rest spread over STREAM_TIME: that is what makes time to first token
                # and generation speed two different numbers.
                time.sleep(FIRST_TOKEN_DELAY)
                pause = STREAM_TIME / max(1, len(chunks))
                for chunk in chunks:
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(pause)
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def plan(self, tool_results_so_far):
        """The chunks of one round, by what the fake model does in this mode."""
        mode = self.mode
        chunks = []

        def call(name, arguments):
            half = max(1, len(arguments) // 2)
            return [
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": f"call_{name}", "type": "function",
                                                        "function": {"name": name, "arguments": ""}}]},
                              "finish_reason": None}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": arguments[:half]}}]},
                              "finish_reason": None}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": arguments[half:]}}]},
                              "finish_reason": None}]},
                {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            ]

        def text():
            return [{"choices": [{"delta": {"content": "Resumen de prueba. "}, "finish_reason": None}]},
                    {"choices": [{"delta": {"content": "Fin."}, "finish_reason": None}]},
                    {"choices": [{"delta": {}, "finish_reason": "stop"}]}]

        if mode == "no_tools":
            chunks = text()
        elif mode == "malformed" and tool_results_so_far == 0:
            chunks = call("ls", "{not json")
        elif tool_results_so_far == 0:
            chunks = call("ls", '{"path": "input"}')
        elif tool_results_so_far == 1:
            chunks = call("read_file", '{"path": "input/piloto_sintetico.txt"}')
        else:
            chunks = text()
        if mode != "no_usage":
            chunks.append({"choices": [], "usage": {"prompt_tokens": 10,
                                                    "completion_tokens": TOKENS_PER_ROUND}})
        return chunks


@pytest.fixture
def server():
    fake = FakeServer()
    yield fake
    fake.stop()


@pytest.fixture
def lms(tmp_path):
    """A fake lms.cmd with state in a folder next to it, and helpers to read it."""
    root = tmp_path / "fake lms"
    (root / "state").mkdir(parents=True)
    (root / "fake_lms.py").write_text(FAKE_LMS, encoding="utf-8")
    (root / "lms.cmd").write_text(f'@"{sys.executable}" "%~dp0fake_lms.py" %*\r\n', encoding="ascii")
    (root / "state" / "calls.log").write_text("", encoding="utf-8")

    class Lms:
        path = str(root / "lms.cmd")

        @staticmethod
        def set_state(loaded=(), ls=LS_TEXT):
            (root / "state" / "state.json").write_text(
                json.dumps({"loaded": list(loaded), "ls": ls}), encoding="utf-8")

        @staticmethod
        def calls():
            return (root / "state" / "calls.log").read_text(encoding="utf-8").splitlines()

    Lms.set_state()
    return Lms


def _quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def powershell(script, timeout=240, **params):
    """Run a script with named parameters through -Command.

    Not -File: with -File every argument arrives as a string and a list such as
    ``-Models a b`` is not bound to a [string[]] (only the first survives, the
    rest is silently positional). -Command parses the line like a console does.
    A switch is ``True``; a list becomes ``'a','b'``.
    """
    parts = ["&", _quote(script)]
    for name, value in params.items():
        if value is True:
            parts.append(f"-{name}")
        elif isinstance(value, (list, tuple)):
            parts.append(f"-{name} " + ",".join(_quote(item) for item in value))
        else:
            parts.append(f"-{name} {_quote(value)}")
    return subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                           " ".join(parts)], capture_output=True, text=True, timeout=timeout)


def bench(lms, server, tmp_path, **params):
    out = tmp_path / "out.json"
    result = powershell(BENCH, Lms=lms.path, BaseUrl=server.url, OutFile=str(out), **params)
    rows = []
    if out.exists():
        data = json.loads(out.read_text(encoding="utf-8-sig"))
        rows = data if isinstance(data, list) else [data]
    return result, rows


# --- bench.ps1 ---------------------------------------------------------------

def test_the_bench_runs_under_windows_powershell_51_and_measures_a_real_tool_loop(
        lms, server, tmp_path):
    result, rows = bench(lms, server, tmp_path, Models=["google/gemma-4-e4b"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(rows) == 1
    row = rows[0]
    assert row["Loaded"] is True
    assert (row["Rounds"], row["Answered"], row["ToolCallsOk"]) == (3, True, True)
    assert row["FirstTokenSeconds"] >= FIRST_TOKEN_DELAY * 0.8
    assert row["TokensEstimated"] is False
    # Generation speed is tokens over the time AFTER the first token, not over the
    # total: 40 tokens in ~0.1 s is hundreds of tok/s; over ~0.7 s it would be ~57.
    assert row["TokensPerSec"] > 150, row["TokensPerSec"]


def test_the_tool_is_executed_and_its_result_goes_back_to_the_model(lms, server, tmp_path):
    bench(lms, server, tmp_path, Models=["google/gemma-4-e4b"])
    assert len(server.requests) == 3
    second = [m for m in server.requests[1]["messages"] if m["role"] == "tool"]
    third = [m for m in server.requests[2]["messages"] if m["role"] == "tool"]
    assert [m["content"] for m in second] == ["piloto_sintetico.txt"]
    assert len(third) == 2 and third[1]["content"].startswith("La empresa ficticia")
    assert all(m["tool_call_id"] for m in third)
    # the assistant turn carries the tool calls it made, as the API requires
    assistant = [m for m in server.requests[2]["messages"] if m["role"] == "assistant"]
    assert [c["function"]["name"] for m in assistant for c in m["tool_calls"]] == ["ls", "read_file"]


def test_a_model_that_never_calls_a_tool_is_not_a_winner(lms, server, tmp_path):
    server.mode = "no_tools"
    _, rows = bench(lms, server, tmp_path, Models=["google/gemma-4-e4b"])
    assert rows[0]["Answered"] is True and rows[0]["ToolCallsOk"] is False


def test_a_tool_call_whose_arguments_are_not_json_is_not_valid(lms, server, tmp_path):
    server.mode = "malformed"
    _, rows = bench(lms, server, tmp_path, Models=["google/gemma-4-e4b"])
    assert rows[0]["ToolCallsOk"] is False


def test_tokens_are_estimated_and_flagged_when_the_server_reports_no_usage(lms, server, tmp_path):
    server.mode = "no_usage"
    _, rows = bench(lms, server, tmp_path, Models=["google/gemma-4-e4b"])
    assert rows[0]["TokensEstimated"] is True and rows[0]["TokensPerSec"] > 0


def test_it_refuses_to_unload_what_the_user_has_loaded(lms, server, tmp_path):
    lms.set_state(loaded=[{"identifier": "qwen/qwen3.8-27b", "model": "qwen/qwen3.8-27b"}])
    result, rows = bench(lms, server, tmp_path, Models=["google/gemma-4-e4b"])
    assert result.returncode != 0
    assert "qwen/qwen3.8-27b" in result.stdout + result.stderr
    assert "-UnloadOthers" in result.stdout + result.stderr
    assert not any(c.startswith(("unload", "load")) for c in lms.calls())
    assert server.requests == []


def test_it_unloads_the_others_only_when_asked_to(lms, server, tmp_path):
    lms.set_state(loaded=[{"identifier": "qwen/qwen3.8-27b", "model": "qwen/qwen3.8-27b"}])
    result, rows = bench(lms, server, tmp_path, Models=["google/gemma-4-e4b"], UnloadOthers=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "unload --all" in lms.calls()


def test_between_candidates_it_unloads_only_what_it_loaded_itself(lms, server, tmp_path):
    result, rows = bench(lms, server, tmp_path, Models=["google/gemma-4-e4b", "openai/gpt-oss-20b"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(rows) == 2 and all(r["Loaded"] for r in rows)
    assert "unload --all" not in lms.calls()
    assert "unload cmh-local" in lms.calls()


def test_by_default_it_measures_the_three_blueprint_candidates_not_the_whole_disk(
        lms, server, tmp_path):
    result, rows = bench(lms, server, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert [r["Model"] for r in rows] == ["google/gemma-4-e4b", "qwen3.5-4b", "phi-4-mini"]
    assert [r["Loaded"] for r in rows] == [True, False, False]
    assert "U4" in rows[1]["Error"]
    real_loads = [c for c in lms.calls() if c.startswith("load ") and "--estimate-only" not in c]
    assert len(real_loads) == 1 and "google/gemma-4-e4b" in real_loads[0]


def test_all_measures_every_llm_on_disk_and_never_the_embedding_model(lms, server, tmp_path):
    result, rows = bench(lms, server, tmp_path, All=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(r["Model"] for r in rows) == [
        "deepseek/deepseek-r1-0528-qwen3-8b", "google/gemma-4-e4b", "openai/gpt-oss-20b",
        "qwen/qwen3.8-27b"]


def test_the_offload_context_and_identifier_are_passed_and_ttl_never_is(lms, server, tmp_path):
    bench(lms, server, tmp_path, Models=["google/gemma-4-e4b"])
    load = [c for c in lms.calls() if c.startswith("load ") and "--estimate-only" not in c][0]
    assert "--gpu 0.5" in load and "-c 16384" in load and "--identifier cmh-local" in load
    assert not any("--ttl" in c for c in lms.calls())


# --- start.ps1 ---------------------------------------------------------------

def start(lms, server, **params):
    return powershell(START, Model="google/gemma-4-e4b", Lms=lms.path, BaseUrl=server.url, **params)


def test_start_unloads_a_single_loaded_model_before_loading(lms, server):
    """The row count used to require MORE than 2 lines, and one loaded model prints
    the header and one row: 2. It did nothing in the exact case it exists for."""
    lms.set_state(loaded=[{"identifier": "qwen/qwen3.8-27b", "model": "qwen/qwen3.8-27b"}])
    result = start(lms, server)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "qwen/qwen3.8-27b" in result.stdout      # it says WHAT it unloads
    calls = lms.calls()
    assert calls.index("unload --all") < next(i for i, c in enumerate(calls) if c.startswith("load "))


def test_start_does_not_unload_when_nothing_is_loaded(lms, server):
    result = start(lms, server)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "unload --all" not in lms.calls()
    assert [c for c in lms.calls() if c.startswith("load ")]


def test_start_loads_with_offload_context_and_identifier_and_without_a_ttl(lms, server):
    start(lms, server)
    load = [c for c in lms.calls() if c.startswith("load ")][0]
    assert "--gpu 0.5" in load and "-c 16384" in load and "--identifier cmh-local" in load
    assert "--ttl" not in load


def test_start_does_nothing_when_the_identifier_is_already_loaded(lms, server):
    lms.set_state(loaded=[{"identifier": "cmh-local", "model": "google/gemma-4-e4b"}])
    result = start(lms, server)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not any(c.startswith(("load", "unload")) for c in lms.calls())


def test_start_stops_cleanly_when_lm_studio_does_not_answer(lms, server):
    server.stop()
    result = start(lms, server)
    assert result.returncode != 0
    assert "LM Studio no responde" in result.stdout + result.stderr
    assert not any(c.startswith(("load", "unload")) for c in lms.calls())
