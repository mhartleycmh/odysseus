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

The independent review of 2026-09-29 then found what those tests still let through:
the bench unloaded the user's ``cmh-local`` by measuring under that very identifier,
took a stream cut in half or a round that spent its tokens reasoning for a final
answer, ignored the exit code of ``lms ls``/``ps``/``unload``, and start.ps1 said
"Listo" without looking. Each is a test below.

These tests run the real scripts with ``powershell.exe`` against a FAKE lms (a
Python script behind a .cmd, writing its progress to stderr like the real one)
and a FAKE OpenAI-compatible server that streams SSE, so nothing touches the
user's LM Studio and nothing is loaded or unloaded on the machine.

Not measured, on purpose: ``$request.Proxy = $null`` in bench.ps1. .NET bypasses the
proxy for a loopback address by itself, so a fake on 127.0.0.1 cannot tell the two
apart, and a listener on a LAN address would raise a firewall prompt.
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


def fails():
    listed = state.get("fail", [])
    if args[0] in listed:
        return True
    if args[0] == "ps" and state.get("ps_fail_after") is not None:
        # `lms ps` answers the first N times and fails from then on
        state["ps_calls"] = state.get("ps_calls", 0) + 1
        save()
        return state["ps_calls"] > state["ps_fail_after"]
    return args[0] == "load" and "--estimate-only" not in args and ("load:" + args[1]) in listed


if fails():
    print("simulated failure of lms " + args[0], file=sys.stderr)
    sys.exit(1)

if args[0] == "ls":
    print(state["ls"])
elif args[0] == "ps":
    loaded = state["loaded"]
    if state.get("raw_ps"):
        # rows printed as given (a row of ONE cell, say): the real format was never seen
        print("")
        print("IDENTIFIER          MODEL               STATUS    SIZE        CONTEXT    PARALLEL    DEVICE    TTL")
        for line in state["raw_ps"]:
            print(line)
    elif not loaded:
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
        if not state.get("noop_load"):
            # the real lms accepts a partial key and `lms ps` then shows the full one
            resolved = state.get("aliases", {}).get(args[1], args[1])
            state["loaded"].append({"identifier": identifier, "model": resolved})
            save()
elif args[0] == "unload":
    print("Unloaded.", file=sys.stderr)
    if len(args) > 1 and args[1] == "--all":
        if not state.get("sticky"):        # a broken lms can say "Unloaded." and keep the models
            state["loaded"] = []
    elif len(args) > 1:
        # an unload that "works" (exit 0) and removes nothing, for the ids in sticky_names
        state["loaded"] = [m for m in state["loaded"]
                           if m["identifier"] != args[1] or args[1] in state.get("sticky_names", [])]
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

GEMMA = "google/gemma-4-e4b"
GPT_OSS = "openai/gpt-oss-20b"
USER_MODEL = {"identifier": "qwen/qwen3.8-27b", "model": "qwen/qwen3.8-27b"}

# Tuned so that generation seconds and total seconds differ enough to tell them apart
# through scheduling jitter: 0.6 s before the first token, 0.1 s of streaming after.
FIRST_TOKEN_DELAY = 0.6
STREAM_TIME = 0.1
TOKENS_PER_ROUND = 40


class FakeServer:
    """A stand-in for LM Studio's OpenAI-compatible API, streaming SSE.

    ``mode`` is what the fake model does. ``script`` overrides it per REQUEST (by its
    index since the server started): ``{"mode": ..., "delay": s, "stream_time": s}``.
    That is how a test gives three candidates three different speeds and behaviours
    through one server.
    """

    def __init__(self):
        self.mode = "good"
        self.script = {}
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
                override = outer.script.get(len(outer.requests) - 1, {})
                mode = override.get("mode", outer.mode)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                tool_messages = [m for m in body["messages"] if m.get("role") == "tool"]
                chunks = outer.plan(len(tool_messages), mode)
                # Nothing on the wire until the "prompt evaluation" is over, then the
                # rest spread over the stream time: that is what makes time to first
                # token and generation speed two different numbers.
                time.sleep(override.get("delay", FIRST_TOKEN_DELAY))
                pause = override.get("stream_time", STREAM_TIME) / max(1, len(chunks))
                for chunk in chunks:
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(pause)
                if mode != "cut":                      # a cut stream just stops
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def plan(self, tool_results_so_far, mode):
        """The chunks of one round, by what the fake model does in this mode."""
        chunks = []

        def call(name, arguments, whole=False):
            if whole:      # a tool call delivered in ONE piece
                return [
                    {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": f"call_{name}",
                                                            "type": "function",
                                                            "function": {"name": name,
                                                                         "arguments": arguments}}]},
                                  "finish_reason": None}]},
                    {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
                ]
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

        whole = mode == "one_chunk"
        if mode == "no_tools":
            chunks = text()
        elif mode == "malformed" and tool_results_so_far == 0:
            chunks = call("ls", "{not json")
        elif tool_results_so_far == 0:
            chunks = call("ls", '{"path": "input"}', whole)
        elif tool_results_so_far == 1:
            chunks = call("read_file", '{"path": "input/piloto_sintetico.txt"}', whole)
        elif mode == "empty":
            # the model says it is done ("stop") and wrote nothing
            chunks = [{"choices": [{"delta": {}, "finish_reason": "stop"}]}]
        elif mode == "cut":
            # the last round: a fragment of text, then the socket just ends
            return [{"choices": [{"delta": {"content": "Resumen incompl"}, "finish_reason": None}]}]
        elif mode == "length":
            # a model that spends every token reasoning and never writes the answer
            chunks = [{"choices": [{"delta": {"reasoning_content": "Pienso... "}, "finish_reason": None}]},
                      {"choices": [{"delta": {"reasoning_content": "sigo pensando."}, "finish_reason": None}]},
                      {"choices": [{"delta": {}, "finish_reason": "length"}]}]
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
        folder = root

        @staticmethod
        def set_state(loaded=(), ls=LS_TEXT, fail=(), noop_load=False, sticky=False,
                      aliases=None, sticky_names=(), ps_fail_after=None, raw_ps=()):
            (root / "state" / "state.json").write_text(
                json.dumps({"loaded": list(loaded), "ls": ls, "fail": list(fail),
                            "noop_load": noop_load, "sticky": sticky,
                            "aliases": aliases or {}, "sticky_names": list(sticky_names),
                            "ps_fail_after": ps_fail_after, "ps_calls": 0,
                            "raw_ps": list(raw_ps)}),
                encoding="utf-8")

        @staticmethod
        def calls():
            return (root / "state" / "calls.log").read_text(encoding="utf-8").splitlines()

        @staticmethod
        def loaded():
            data = json.loads((root / "state" / "state.json").read_text(encoding="utf-8"))
            return [m["identifier"] for m in data["loaded"]]

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


def powershell_file(script, timeout=240, **params):
    """Run a script through -File, as the documented command does: every argument arrives as
    ONE string and a switch is a bare flag."""
    args = []
    for name, value in params.items():
        args.append(f"-{name}")
        if value is not True:
            args.append(str(value))
    return subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                           str(script), *args], capture_output=True, text=True, timeout=timeout)


def bench(lms, server, tmp_path, **params):
    out = tmp_path / "out.json"
    result = powershell(BENCH, Lms=lms.path, BaseUrl=server.url, OutFile=str(out), **params)
    rows = []
    if out.exists():
        data = json.loads(out.read_text(encoding="utf-8-sig"))
        rows = data if isinstance(data, list) else [data]
    return result, rows


def said(result):
    return result.stdout + result.stderr


# --- how the scripts are run on THIS machine ----------------------------------

def _example_section(path):
    text = path.read_text(encoding="utf-8")
    return text[text.index(".EXAMPLE"):text.index("#>")]


@pytest.mark.parametrize("script", [BENCH, START])
def test_the_help_documents_the_command_that_actually_starts_on_this_machine(script):
    """Get-ExecutionPolicy is Restricted here: without -ExecutionPolicy Bypass the .ps1
    does not run one line. The tests force Bypass, which is exactly what hid it."""
    examples = [line.strip() for line in _example_section(script).splitlines()
                if "powershell" in line]
    assert examples and all("-ExecutionPolicy Bypass" in line for line in examples), examples


@pytest.mark.parametrize("name", ["bench", "start"])
def test_each_ps1_has_a_posix_wrapper_that_passes_bypass(name):
    wrapper = REPO / "scripts" / "cmh_local" / f"{name}.sh"
    text = wrapper.read_text(encoding="utf-8")
    assert "-ExecutionPolicy Bypass" in text and f"{name}.ps1" in text and '"$@"' in text


# --- bench.ps1 ---------------------------------------------------------------

def test_the_bench_runs_under_windows_powershell_51_and_measures_a_real_tool_loop(
        lms, server, tmp_path):
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA])
    assert result.returncode == 0, said(result)
    assert len(rows) == 1
    row = rows[0]
    assert row["Loaded"] is True
    assert (row["Rounds"], row["Answered"], row["ToolCallsOk"]) == (3, True, True)
    assert row["FirstTokenSeconds"] >= FIRST_TOKEN_DELAY * 0.8
    assert row["TokensEstimated"] is False
    # Generation speed is tokens over the time AFTER the first token, not over the
    # total. The two are compared inside the same run, so a busy machine slows both
    # and the ratio survives: ~0.1 s against ~0.7 s per round is a factor of about 7.
    assert row["TokensPerSec"] > 2 * row["TotalTokensPerSec"], (row["TokensPerSec"],
                                                                  row["TotalTokensPerSec"])


def test_the_tool_is_executed_and_its_result_goes_back_to_the_model(lms, server, tmp_path):
    bench(lms, server, tmp_path, Models=[GEMMA])
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
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA])
    assert rows[0]["Answered"] is True and rows[0]["ToolCallsOk"] is False
    assert result.returncode == 1 and "Ganador" not in said(result)      # nobody passed


def test_a_tool_call_whose_arguments_are_not_json_is_not_valid(lms, server, tmp_path):
    server.mode = "malformed"
    _, rows = bench(lms, server, tmp_path, Models=[GEMMA])
    assert rows[0]["ToolCallsOk"] is False


def test_tokens_are_estimated_and_flagged_when_the_server_reports_no_usage(lms, server, tmp_path):
    server.mode = "no_usage"
    _, rows = bench(lms, server, tmp_path, Models=[GEMMA])
    assert rows[0]["TokensEstimated"] is True and rows[0]["TokensPerSec"] > 0


# --- what counts as a final answer ---------------------------------------------

def test_a_stream_cut_in_half_is_not_a_final_answer_and_nobody_wins(lms, server, tmp_path):
    """No finish_reason and no [DONE]: the socket just ended after 'Resumen incompl'. It
    used to be an answer because the round carried no tool call, and the bench announced
    a winner with 'tool calling valido y respuesta final'."""
    server.mode = "cut"
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA])
    assert (rows[0]["Answered"], rows[0]["ToolCallsOk"]) == (False, False)
    assert "sin respuesta final" in rows[0]["Error"]
    assert result.returncode == 1 and "Ganador" not in said(result)


def test_a_round_that_spent_max_tokens_reasoning_is_not_a_final_answer(lms, server, tmp_path):
    """finish_reason 'length' and no text, only reasoning: the case a thinking model (the
    second candidate, Qwen3.5-4B, is one) reaches at a low max_tokens."""
    server.mode = "length"
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA])
    assert (rows[0]["Answered"], rows[0]["ToolCallsOk"]) == (False, False)
    assert "finish='length'" in rows[0]["Error"]
    assert result.returncode == 1 and "Ganador" not in said(result)


def test_an_empty_answer_is_not_an_answer(lms, server, tmp_path):
    """finish_reason 'stop' with no text at all: the model said it was done and wrote nothing."""
    server.mode = "empty"
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA])
    assert (rows[0]["Answered"], rows[0]["ToolCallsOk"]) == (False, False)
    assert "0 caracteres" in rows[0]["Error"]
    assert result.returncode == 1


def test_max_tokens_is_a_parameter_with_room_to_think(lms, server, tmp_path):
    bench(lms, server, tmp_path, Models=[GEMMA])
    assert {r["max_tokens"] for r in server.requests} == {1024}
    server.requests.clear()
    bench(lms, server, tmp_path, Models=[GEMMA], MaxTokens=2048)
    assert {r["max_tokens"] for r in server.requests} == {2048}


# --- the tok/s is not inflated by a round the server delivers in one piece -----------

def test_a_tool_call_delivered_in_one_piece_does_not_inflate_the_generation_speed(
        lms, server, tmp_path):
    """Its tokens went into the numerator and its time stayed in 'time to first token', so
    the speed that picks the winner was inflated. A round that arrives in fewer than 3
    pieces has no measurable rate and does not count."""
    server.mode = "one_chunk"
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA])
    row = rows[0]
    assert row["ToolCallsOk"] is True and row["Answered"] is True
    assert row["TokensPerSec"] is None                 # nothing measurable, not "very fast"
    assert row["TotalTokensPerSec"] > 0                # the total is still there, to compare
    assert result.returncode == 0                       # it passed, and is the only candidate


def test_time_to_first_token_is_the_one_of_the_first_round(lms, server, tmp_path):
    server.script = {0: {"delay": 1.4}}               # the first request waits longer
    _, rows = bench(lms, server, tmp_path, Models=[GEMMA])
    assert rows[0]["FirstTokenSeconds"] >= 1.2         # the last round would say ~0.6


# --- the winner ------------------------------------------------------------------------

def _three_candidates(server):
    """A: fastest but its first tool call is malformed. B: valid and slow. C: valid, faster
    than B. Requests 0-2 are A's, 3-5 B's, 6-8 C's."""
    server.script = {
        0: {"mode": "malformed", "stream_time": 0.05}, 1: {"mode": "malformed", "stream_time": 0.05},
        2: {"mode": "malformed", "stream_time": 0.05},
        3: {"stream_time": 0.4}, 4: {"stream_time": 0.4}, 5: {"stream_time": 0.4},
        6: {"stream_time": 0.15}, 7: {"stream_time": 0.15}, 8: {"stream_time": 0.15},
    }


def test_the_winner_is_the_fastest_candidate_that_passes_the_tool_check(lms, server, tmp_path):
    _three_candidates(server)
    result, rows = bench(lms, server, tmp_path, Models=["cand/a", "cand/b", "cand/c"])
    assert result.returncode == 0, said(result)
    by_model = {r["Model"]: r for r in rows}
    # A really is the fastest, so only the tool check keeps it from winning
    assert by_model["cand/a"]["ToolCallsOk"] is False
    assert by_model["cand/a"]["TokensPerSec"] > by_model["cand/c"]["TokensPerSec"] > by_model["cand/b"]["TokensPerSec"]
    assert "Ganador: cand/c" in said(result)


# --- what happens to what is loaded ---------------------------------------------------

def test_it_refuses_to_unload_what_the_user_has_loaded(lms, server, tmp_path):
    lms.set_state(loaded=[USER_MODEL])
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA])
    assert result.returncode != 0
    assert "qwen/qwen3.8-27b" in said(result)
    assert "-UnloadOthers" in said(result)
    assert not any(c.startswith(("unload", "load")) for c in lms.calls())
    assert server.requests == []


def test_it_unloads_the_others_only_when_asked_to(lms, server, tmp_path):
    lms.set_state(loaded=[USER_MODEL])
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA], UnloadOthers=True)
    assert result.returncode == 0, said(result)
    assert "unload --all" in lms.calls()


def test_the_local_fallback_that_start_loaded_is_not_touched_without_the_switch(lms, server, tmp_path):
    """The bench measured under 'cmh-local' and unloaded that identifier before every
    candidate and at the end: it destroyed exactly what start.ps1 leaves loaded as the
    router's fallback, and the fallback answered 404 until start.ps1 was run again."""
    lms.set_state(loaded=[{"identifier": "cmh-local", "model": GEMMA}])
    result, _ = bench(lms, server, tmp_path, Models=[GEMMA])
    assert result.returncode != 0
    assert "cmh-local" in said(result) and "-UnloadOthers" in said(result)
    assert not any(c.startswith(("unload", "load")) for c in lms.calls())
    assert lms.loaded() == ["cmh-local"] and server.requests == []


def test_the_bench_never_unloads_cmh_local_by_name_and_measures_under_its_own_identifier(
        lms, server, tmp_path):
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA, GPT_OSS])
    assert result.returncode == 0, said(result)
    assert len(rows) == 2 and all(r["Loaded"] for r in rows)
    calls = lms.calls()
    assert "unload --all" not in calls
    assert "unload cmh-bench" in calls and "unload cmh-local" not in calls
    assert lms.loaded() == []                           # it left nothing behind


def test_by_default_it_measures_the_three_blueprint_candidates_not_the_whole_disk(
        lms, server, tmp_path):
    result, rows = bench(lms, server, tmp_path)
    assert result.returncode == 0, said(result)
    assert [r["Model"] for r in rows] == [GEMMA, "qwen3.5-4b", "phi-4-mini"]
    assert [r["Loaded"] for r in rows] == [True, False, False]
    assert "U4" in rows[1]["Error"]
    real_loads = [c for c in lms.calls() if c.startswith("load ") and "--estimate-only" not in c]
    assert len(real_loads) == 1 and GEMMA in real_loads[0]


def test_all_measures_every_llm_on_disk_and_never_the_embedding_model(lms, server, tmp_path):
    result, rows = bench(lms, server, tmp_path, All=True)
    assert result.returncode == 0, said(result)
    assert sorted(r["Model"] for r in rows) == [
        "deepseek/deepseek-r1-0528-qwen3-8b", GEMMA, GPT_OSS, "qwen/qwen3.8-27b"]


def test_the_offload_context_and_identifier_are_passed_and_ttl_never_is(lms, server, tmp_path):
    bench(lms, server, tmp_path, Models=[GEMMA])
    load = [c for c in lms.calls() if c.startswith("load ") and "--estimate-only" not in c][0]
    assert "--gpu 0.5" in load and "-c 16384" in load and "--identifier cmh-bench" in load
    assert not any("--ttl" in c for c in lms.calls())


@pytest.mark.parametrize("separator", [",", ", "])
def test_a_comma_separated_list_binds_as_several_models_even_through_file(
        lms, server, tmp_path, separator):
    """With -File a list arrives as ONE string ('a,b'); the script splits it and trims each
    piece. The documented command says "a, b" works, and the test used to run through
    -Command with no space, so neither the -File path nor the Trim() was ever exercised."""
    out = tmp_path / "out.json"
    result = powershell_file(BENCH, Lms=lms.path, BaseUrl=server.url, OutFile=out,
                             Models=f"{GEMMA}{separator}{GPT_OSS}")
    assert result.returncode == 0, said(result)
    rows = json.loads(out.read_text(encoding="utf-8-sig"))
    assert [r["Model"] for r in rows] == [GEMMA, GPT_OSS]


# --- lms failing is not lms saying "nothing" ------------------------------------------

def test_a_failing_lms_ls_stops_the_bench_with_its_error_and_not_a_diagnosis(lms, server, tmp_path):
    lms.set_state(fail=["ls"])
    result, rows = bench(lms, server, tmp_path)
    assert result.returncode != 0 and rows == []
    assert "lms ls fallo" in said(result) and "simulated failure of lms ls" in said(result)
    assert "no esta en disco" not in said(result)
    assert server.requests == []


def test_a_failing_lms_ps_stops_the_bench(lms, server, tmp_path):
    lms.set_state(fail=["ps"])
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA])
    assert result.returncode != 0 and "lms ps fallo" in said(result)
    assert server.requests == []


def test_a_failing_unload_stops_the_bench_before_it_measures_anything(lms, server, tmp_path):
    lms.set_state(loaded=[USER_MODEL], fail=["unload"])
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA], UnloadOthers=True)
    assert result.returncode != 0 and "unload --all fallo" in said(result)
    assert server.requests == [] and lms.loaded() == ["qwen/qwen3.8-27b"]


def test_the_bench_stops_if_something_stays_loaded_after_the_unload(lms, server, tmp_path):
    """lms said 'Unloaded.' and exited 0, and the user's model is still in the shared memory:
    measuring on top of it contaminates every number."""
    lms.set_state(loaded=[USER_MODEL], sticky=True)
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA], UnloadOthers=True)
    assert result.returncode != 0 and "siguen cargados" in said(result)
    assert server.requests == []


def test_a_candidate_that_does_not_load_is_reported_and_the_next_one_is_measured(
        lms, server, tmp_path):
    lms.set_state(fail=[f"load:{GEMMA}"])
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA, GPT_OSS])
    assert result.returncode == 0, said(result)
    assert rows[0]["Loaded"] is False and "simulated failure of lms load" in rows[0]["Error"]
    assert rows[1]["Loaded"] is True and rows[1]["ToolCallsOk"] is True
    assert "NO CARGA" in said(result) and "Ganador: openai/gpt-oss-20b" in said(result)


@pytest.mark.parametrize("script, extra", [(BENCH, {"Models": [GEMMA]}), (START, {"Model": GEMMA})])
def test_an_lms_path_with_square_brackets_is_found(lms, server, tmp_path, script, extra):
    """Test-Path reads '[' and ']' as a wildcard class: an existing path with brackets was
    reported as 'No se encuentra lms'."""
    odd = tmp_path / "lms [1] v2"
    shutil.copytree(lms.folder, odd)
    params = dict(extra, Lms=str(odd / "lms.cmd"), BaseUrl=server.url)
    result = powershell(script, **params)
    assert "No se encuentra lms" not in said(result), said(result)
    assert result.returncode == 0, said(result)


# --- start.ps1 ---------------------------------------------------------------

def start(lms, server, model=GEMMA, **params):
    return powershell(START, Model=model, Lms=lms.path, BaseUrl=server.url, **params)


def test_start_unloads_a_single_loaded_model_before_loading_when_asked(lms, server):
    """The row count used to require MORE than 2 lines, and one loaded model prints
    the header and one row: 2. It did nothing in the exact case it exists for."""
    lms.set_state(loaded=[USER_MODEL])
    result = start(lms, server, UnloadOthers=True)
    assert result.returncode == 0, said(result)
    assert "qwen/qwen3.8-27b" in result.stdout      # it says WHAT it unloads
    calls = lms.calls()
    assert calls.index("unload --all") < next(i for i, c in enumerate(calls) if c.startswith("load "))
    assert lms.loaded() == ["cmh-local"]


def test_start_refuses_to_unload_what_the_user_has_loaded_without_the_switch(lms, server):
    """ADR-033's title said the scripts do not touch what they did not load. start.ps1 ran
    `lms unload --all` on whatever was there, with a notice and no consent."""
    lms.set_state(loaded=[USER_MODEL])
    result = start(lms, server)
    assert result.returncode != 0
    assert "qwen/qwen3.8-27b" in said(result) and "-UnloadOthers" in said(result)
    assert not any(c.startswith(("unload", "load")) for c in lms.calls())
    assert lms.loaded() == ["qwen/qwen3.8-27b"]


def test_start_does_not_unload_when_nothing_is_loaded(lms, server):
    result = start(lms, server)
    assert result.returncode == 0, said(result)
    assert "unload --all" not in lms.calls()
    assert [c for c in lms.calls() if c.startswith("load ")]


def test_start_loads_with_offload_context_and_identifier_and_without_a_ttl(lms, server):
    start(lms, server)
    load = [c for c in lms.calls() if c.startswith("load ")][0]
    assert "--gpu 0.5" in load and "-c 16384" in load and "--identifier cmh-local" in load
    assert "--ttl" not in load


def test_start_does_nothing_when_the_identifier_is_already_loaded_with_that_model(lms, server):
    lms.set_state(loaded=[{"identifier": "cmh-local", "model": GEMMA}])
    result = start(lms, server)
    assert result.returncode == 0, said(result)
    assert not any(c.startswith(("load", "unload")) for c in lms.calls())


def test_start_checks_the_model_behind_an_identifier_that_is_already_loaded(lms, server):
    """It compared only the identifier: 'cmh-local' served by ANY model was 'Ya esta cargado'."""
    lms.set_state(loaded=[{"identifier": "cmh-local", "model": "other/model"}])
    refused = start(lms, server)
    assert refused.returncode != 0
    assert "other/model" in said(refused) and "-UnloadOthers" in said(refused)
    assert not any(c.startswith(("load", "unload")) for c in lms.calls())

    replaced = start(lms, server, UnloadOthers=True)
    assert replaced.returncode == 0, said(replaced)
    calls = lms.calls()
    assert "unload --all" in calls and any(c.startswith("load ") and GEMMA in c for c in calls)


def test_start_stops_cleanly_when_lm_studio_does_not_answer(lms, server):
    server.stop()
    result = start(lms, server)
    assert result.returncode != 0
    assert "LM Studio no responde" in said(result)
    assert not any(c.startswith(("load", "unload")) for c in lms.calls())


def test_start_stops_when_lms_ps_fails(lms, server):
    lms.set_state(fail=["ps"])
    result = start(lms, server)
    assert result.returncode != 0 and "lms ps fallo" in said(result)
    assert not any(c.startswith(("load", "unload")) for c in lms.calls())


def test_start_stops_when_the_unload_fails_and_does_not_load_on_top(lms, server):
    lms.set_state(loaded=[USER_MODEL], fail=["unload"])
    result = start(lms, server, UnloadOthers=True)
    assert result.returncode != 0 and "unload --all fallo" in said(result)
    assert not any(c.startswith("load ") for c in lms.calls())
    assert "Listo" not in result.stdout


def test_start_stops_if_the_unload_did_not_free_the_memory(lms, server):
    """The unload exits 0 but the other model is still loaded: loading on top of it leaves
    two models in the shared memory and 'Listo' would be a lie."""
    lms.set_state(loaded=[USER_MODEL], sticky=True)
    result = start(lms, server, UnloadOthers=True)
    assert result.returncode != 0 and "Quedaron cargados" in said(result)
    assert "Listo" not in result.stdout


def test_start_reports_a_failed_load_and_does_not_say_it_is_ready(lms, server):
    lms.set_state(fail=[f"load:{GEMMA}"])
    result = start(lms, server)
    assert result.returncode != 0
    assert "La carga fallo con exit 1" in said(result) and "Listo" not in result.stdout


def test_start_does_not_say_ready_unless_cmh_local_is_actually_loaded(lms, server):
    """lms exits 0 but nothing is loaded afterwards: 'Listo' needs `lms ps` to agree."""
    lms.set_state(noop_load=True)
    result = start(lms, server)
    assert result.returncode != 0
    assert "no aparece" in said(result) and "Listo" not in result.stdout


# --- review of revision-fase1-r7 ---------------------------------------------------------------

def test_bench_refuses_to_measure_under_the_identifier_of_the_routers_fallback(lms, server, tmp_path):
    """-Identifier cmh-local reopened by another door the defect of measuring under the name
    start.ps1 leaves loaded: the loaded cmh-local counted as the bench's own and was unloaded."""
    lms.set_state(loaded=[{"identifier": "cmh-local", "model": GEMMA}])
    result, _ = bench(lms, server, tmp_path, Models=[GEMMA], Identifier="cmh-local")
    assert result.returncode != 0 and "respaldo local del router" in said(result)
    assert lms.calls() == [] and server.requests == []
    assert lms.loaded() == ["cmh-local"]


def test_bench_stops_when_its_own_identifier_is_still_loaded_after_an_unload(lms, server, tmp_path):
    """The real lms exits 0 for 'Model Not Found', so an unload that removed nothing looks like
    one that worked; the next candidate would be measured on top of the previous one."""
    lms.set_state(sticky_names=["cmh-bench"])
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA, GPT_OSS])
    assert result.returncode != 0 and "no lo descargo" in said(result)
    assert len(server.requests) == 3                       # only the first candidate was measured
    loads = [c for c in lms.calls() if c.startswith("load ") and "--estimate-only" not in c]
    assert len(loads) == 1


def test_a_leftover_cmh_bench_from_a_crashed_run_is_its_own_and_is_said(lms, server, tmp_path):
    lms.set_state(loaded=[{"identifier": "cmh-bench", "model": "old/model"}])
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA])
    assert result.returncode == 0, said(result)             # no -UnloadOthers needed for it
    assert "de una corrida anterior" in said(result)
    assert lms.loaded() == []


def test_a_leftover_cmh_bench_does_not_count_as_somebody_elses_model(lms, server, tmp_path):
    lms.set_state(loaded=[{"identifier": "cmh-bench", "model": "old/model"}, USER_MODEL])
    result, _ = bench(lms, server, tmp_path, Models=[GEMMA])
    assert result.returncode != 0 and "qwen/qwen3.8-27b" in said(result)
    assert "Hay modelos cargados que este banco descargaria: qwen/qwen3.8-27b." in said(result)
    assert server.requests == []


def test_the_rate_leaves_out_the_first_token_of_each_measured_round(lms, server, tmp_path):
    """Two tool rounds arrive in 3 pieces (the text round in 2 and does not count), each with
    40 tokens: the numerator is 2 x (40 - 1) = 78, and what is printed is that over the time."""
    _, rows = bench(lms, server, tmp_path, Models=[GEMMA])
    row = rows[0]
    assert row["RateTokens"] == 78
    assert row["RateSeconds"] > 0
    assert abs(row["TokensPerSec"] - round(row["RateTokens"] / row["RateSeconds"], 2)) < 1.0


def test_a_model_with_no_measurable_speed_ranks_last_and_the_output_says_so(lms, server, tmp_path):
    """A delivers every round in one piece (nothing measurable) and B streams. B wins; and
    when A is the only one that passes, the line says 'no medible' instead of a blank."""
    server.script = {0: {"mode": "one_chunk"}, 1: {"mode": "one_chunk"}, 2: {"mode": "one_chunk"}}
    result, rows = bench(lms, server, tmp_path, Models=["cand/a", "cand/b"])
    by_model = {r["Model"]: r for r in rows}
    assert by_model["cand/a"]["TokensPerSec"] is None and by_model["cand/b"]["TokensPerSec"] > 0
    assert "Ganador: cand/b" in said(result)

    server.script, server.requests = {}, []
    server.mode = "one_chunk"
    lms.set_state()
    alone, _ = bench(lms, server, tmp_path, Models=[GEMMA])
    assert "velocidad no medible" in said(alone) and "-  tok/s" not in said(alone)


# --- start.ps1: the model behind cmh-local ---------------------------------------------------

def test_start_accepts_a_partial_key_that_lms_resolved(lms, server):
    """lms loads 'gemma-4-e4b' as google/gemma-4-e4b and `lms ps` prints the full key. The
    check by string equality failed a load that had worked, and asked for -UnloadOthers to
    'replace' the very model that was wanted."""
    lms.set_state(aliases={"gemma-4-e4b": GEMMA})
    first = start(lms, server, model="gemma-4-e4b")
    assert first.returncode == 0 and "Listo" in first.stdout, said(first)
    assert lms.loaded() == ["cmh-local"]
    calls_before = len(lms.calls())
    again = start(lms, server, model="gemma-4-e4b")
    assert again.returncode == 0 and "Ya esta cargado" in again.stdout, said(again)
    assert not any(c.startswith(("load", "unload")) for c in lms.calls()[calls_before:])


def test_start_accepts_a_model_key_with_spaces(lms, server):
    """`lms ps` is read by whitespace: a key with spaces reaches the check in pieces."""
    key = "my-org/My Model Name"
    result = start(lms, server, model=key)
    assert result.returncode == 0 and "Listo" in result.stdout, said(result)


def test_start_does_not_take_an_unrelated_model_for_the_one_asked(lms, server):
    lms.set_state(loaded=[{"identifier": "cmh-local", "model": "qwen/qwen3.8-27b"}])
    result = start(lms, server)
    assert result.returncode != 0 and "qwen/qwen3.8-27b" in said(result)
    assert not any(c.startswith(("load", "unload")) for c in lms.calls())


def test_start_does_not_say_already_loaded_while_another_model_shares_the_memory(lms, server):
    """cmh-local is the right model but the user's own model is loaded next to it: it is NOT
    'nothing to do', it is the shared-memory situation -UnloadOthers exists for."""
    lms.set_state(loaded=[{"identifier": "cmh-local", "model": GEMMA}, USER_MODEL])
    result = start(lms, server)
    assert result.returncode != 0 and "qwen/qwen3.8-27b" in said(result)
    assert "Ya esta cargado" not in result.stdout
    assert not any(c.startswith(("load", "unload")) for c in lms.calls())


# --- start.ps1, r9: a model that merely CONTAINS the one asked is not the one asked -----------
#
# The third review (revision-fase1-r8) measured that the comparison of r8 (one key contained in
# the other, in both directions) declared "Ya esta cargado" for microsoft/phi-4-mini-reasoning
# when phi-4-mini was asked, and left the script exiting 0 with nothing loaded. Three rules
# remain: the same key, the same key without its publisher on one side, and the first word of a
# key with spaces. Each case below is tied to the rule it keeps honest.

@pytest.mark.parametrize("loaded_model, asked", [
    ("microsoft/phi-4-mini-reasoning", "phi-4-mini"),       # the asked key inside the loaded one
    ("phi-4-mini", "microsoft/phi-4-mini-reasoning"),       # the loaded key inside the asked one
    ("qwen3-4b", "qwen3-4b-2507"),                          # a version suffix on the asked key
    ("phi-4-mini", "phi-4-mini-reasoning"),                 # a free prefix: no publisher, no space
    ("google/gemma-4-e4b", "gemma-4"),                      # the asked key is a prefix of the name
    ("unsloth/vl-qwen3-4b", "qwen3-4b"),                    # the name ends with the asked key but is another model
    ("microsoft/phi-4-mini", "unsloth/phi-4-mini"),         # the same name from ANOTHER publisher
    ("microsoft/tinyphi-4-mini", "phi-4-mini"),
    ("x-phi-4-mini", "phi-4-mini"),                         # no slash: a longer name, not a publisher
    ("phi-4-mini", "x-phi-4-mini"),
    ("qwen3-4b", "unsloth/vl-qwen3-4b"),
], ids=["asked-inside-loaded", "loaded-inside-asked", "version-suffix", "free-prefix", "name-prefix",
        "suffix-of-another-model", "other-publisher", "tinyphi", "no-slash", "no-slash-reversed",
        "suffix-reversed"])
def test_start_does_not_take_a_model_that_merely_contains_the_one_asked(
        lms, server, loaded_model, asked):
    lms.set_state(loaded=[{"identifier": "cmh-local", "model": loaded_model}])
    refused = start(lms, server, model=asked)
    assert refused.returncode != 0, said(refused)
    assert loaded_model in said(refused) and "-UnloadOthers" in said(refused)
    assert "Ya esta cargado" not in refused.stdout
    assert not any(c.startswith(("load", "unload")) for c in lms.calls())

    replaced = start(lms, server, model=asked, UnloadOthers=True)
    assert replaced.returncode == 0, said(replaced)
    calls = lms.calls()
    assert "unload --all" in calls and any(c.startswith("load ") and asked in c for c in calls)


@pytest.mark.parametrize("loaded_model, asked", [
    ("gemma-4-e4b", "google/gemma-4-e4b"),                  # loaded without publisher, asked with it
    ("google/gemma-4-e4b", "GOOGLE/Gemma-4-E4B"),           # the same key in other capitals
], ids=["publisher-only-when-asked", "other-capitals"])
def test_start_takes_the_same_key_with_or_without_its_publisher_or_in_other_capitals(
        lms, server, loaded_model, asked):
    lms.set_state(loaded=[{"identifier": "cmh-local", "model": loaded_model}])
    result = start(lms, server, model=asked)
    assert result.returncode == 0 and "Ya esta cargado" in result.stdout, said(result)
    assert not any(c.startswith(("load", "unload")) for c in lms.calls())


# --- bench.ps1, r9: a cleanup that fails must not throw away what was measured ----------------
#
# The third review (revision-fase1-r8) measured that r8's Remove-Own re-read `lms ps` with no
# guard: when that call failed, the script aborted with no table and no -OutFile, which r7
# still produced. `lms ps` is called at the start, before each candidate and at the end: a
# ps_fail_after of 2 lets the first two through and fails from the third on.

def test_a_failing_lms_ps_at_the_end_keeps_the_measurement_and_says_it_could_not_check(
        lms, server, tmp_path):
    lms.set_state(ps_fail_after=2)              # start, before the only candidate; the end fails
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA])
    assert result.returncode == 0, said(result)                # there is a winner
    assert len(rows) == 1 and rows[0]["ToolCallsOk"] is True
    assert "no se pudo comprobar" in said(result) and "lms ps" in said(result)


def test_a_failing_lms_ps_between_candidates_stops_the_bench_but_keeps_the_first_row(
        lms, server, tmp_path):
    lms.set_state(ps_fail_after=2)              # start, before candidate 1; before candidate 2 fails
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA, GPT_OSS])
    assert result.returncode != 0, said(result)
    assert [r["Model"] for r in rows] == [GEMMA, GPT_OSS]
    assert rows[0]["ToolCallsOk"] is True and rows[1]["Loaded"] is False
    assert "no se pudo comprobar" in said(result)
    assert "se detuvo antes de medirlo todo" in said(result)


def test_a_stop_for_an_unload_that_unloads_nothing_keeps_what_was_measured_and_says_how_to_clean_up(
        lms, server, tmp_path):
    lms.set_state(sticky_names=["cmh-bench"])
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA, GPT_OSS])
    assert result.returncode != 0, said(result)
    assert len(rows) == 2 and rows[0]["ToolCallsOk"] is True and rows[1]["Loaded"] is False
    assert "lms unload cmh-bench" in said(result)
    assert len(server.requests) == 3                    # the second candidate was never measured


def test_the_bench_warns_when_its_identifier_is_still_loaded_at_the_end(lms, server, tmp_path):
    lms.set_state(sticky_names=["cmh-bench"])
    result, rows = bench(lms, server, tmp_path, Models=[GEMMA])
    assert result.returncode == 0, said(result)                # a winner exists
    assert "AVISO" in said(result) and "lms unload cmh-bench" in said(result)
    assert "cmh-bench" in lms.loaded()


def test_an_identifier_that_was_already_loaded_and_is_not_the_default_belongs_to_the_user(
        lms, server, tmp_path):
    """Only 'cmh-bench' is the bench's own leftover. The message said a model the user had
    loaded under -Identifier was 'de una corrida anterior' and unloaded it without the switch."""
    lms.set_state(loaded=[USER_MODEL])
    result, _ = bench(lms, server, tmp_path, Models=[GEMMA], Identifier="qwen/qwen3.8-27b")
    assert result.returncode != 0 and "-UnloadOthers" in said(result)
    assert "de una corrida anterior" not in said(result)
    assert lms.loaded() == ["qwen/qwen3.8-27b"] and server.requests == []


def test_bench_guards_both_the_identifier_in_the_config_and_the_default_cmh_local(
        lms, server, tmp_path):
    """start.ps1 loads under 'cmh-local' whatever the config says, so the guard covers the two.
    The script reads config/cmh_free_quotas.json relative to itself: a copy in a tree of its own."""
    tree = tmp_path / "tree"
    (tree / "scripts" / "cmh_local").mkdir(parents=True)
    (tree / "config").mkdir()
    script = tree / "scripts" / "cmh_local" / "bench.ps1"
    script.write_bytes(BENCH.read_bytes())
    (tree / "config" / "cmh_free_quotas.json").write_text(
        json.dumps({"local": {"model": "lm-router"}}), encoding="utf-8")
    for identifier in ("lm-router", "cmh-local"):
        result = powershell(str(script), Lms=lms.path, BaseUrl=server.url, Models=[GEMMA],
                            Identifier=identifier)
        assert result.returncode != 0 and "respaldo local del router" in said(result), identifier
    assert lms.calls() == [] and server.requests == []


# --- start.ps1, r10 (fourth review of revision-fase1-r9) -----------------------------------------
#
# r9 kept a third rule (the first word of a key with spaces) that took ".../My Model Q8" for
# ".../My Model Q4", and it compared the model AFTER its own load, so a partial key that lms
# resolves by prefix ("gemma-4", "qwen3.5") failed after a load that had worked. Now only the two
# exact rules decide whether to skip a load; after a load of its own the script accepts what lms
# put under cmh-local and PRINTS it.

@pytest.mark.parametrize("loaded_model, asked", [
    ("my-org/My Model Q8", "my-org/My Model Q4"),           # the same first words, another model
    ("phi", "phi 4 mini"),
    ("gemma", "gemma 4 e4b"),
], ids=["same-first-words", "one-word-prefix", "one-word-prefix-2"])
def test_start_does_not_take_a_key_with_spaces_for_another_that_shares_its_first_words(
        lms, server, loaded_model, asked):
    lms.set_state(loaded=[{"identifier": "cmh-local", "model": loaded_model}])
    refused = start(lms, server, model=asked)
    assert refused.returncode != 0, said(refused)
    assert "Ya esta cargado" not in refused.stdout and "-UnloadOthers" in said(refused)
    assert not any(c.startswith(("load", "unload")) for c in lms.calls())
    replaced = start(lms, server, model=asked, UnloadOthers=True)
    assert replaced.returncode == 0, said(replaced)
    calls = lms.calls()
    assert "unload --all" in calls and any(c.startswith("load ") and asked in c for c in calls)


@pytest.mark.parametrize("asked, resolved", [
    ("gemma-4", GEMMA),                  # a prefix of the name: lms loads "the first one"
    ("e4b", GEMMA),                      # an infix
    ("qwen3.5", "qwen/qwen3.5-9b"),
], ids=["prefix", "infix", "version-prefix"])
def test_start_accepts_what_lms_resolved_from_a_partial_key_after_loading_and_says_it(
        lms, server, asked, resolved):
    lms.set_state(aliases={asked: resolved})
    result = start(lms, server, model=asked)
    assert result.returncode == 0 and "Listo" in result.stdout, said(result)
    assert resolved in result.stdout                         # it prints what lms loaded
    assert "AVISO" in result.stdout and "clave completa" in result.stdout


def test_start_does_not_warn_when_what_lms_loaded_is_the_key_that_was_asked(lms, server):
    result = start(lms, server)
    assert result.returncode == 0 and "AVISO" not in result.stdout, said(result)


def test_a_row_of_lms_ps_with_one_cell_is_not_a_model_and_is_never_taken_for_the_one_asked(
        lms, server):
    """No model cell: both sides must be non-empty for any rule to match. With the guard
    removed, 'google/' ends with the '/' that '' + '/' gives, and the script said 'Ya esta
    cargado' about a row that names no model."""
    lms.set_state(raw_ps=["cmh-local"])
    result = start(lms, server, model="google/")
    assert result.returncode != 0, said(result)
    assert "Ya esta cargado" not in result.stdout and "-UnloadOthers" in said(result)
    assert not any(c.startswith(("load", "unload")) for c in lms.calls())
