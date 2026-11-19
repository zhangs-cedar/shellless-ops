"""Compare three diagnostic turns on one fixture per trial.

Run from this directory with: .venv/bin/python benchmark.py
"""

import argparse
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import random
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter


NAMES = ("record_id", "missing_field")
LOAD = """\
import json
from pathlib import Path
raw = Path({fixture!r}).read_text(encoding="utf-8")
with Path({audit!r}).open("ab") as load_log:
    load_log.write(b"1\\n")
records = json.loads(raw)
"""
LOADED = 'print(f"loaded {len(records)} records")'
FAIL = """\
def total_amount(records):
    total = 0
    for row in records:
        record_id = row["id"]
        missing_field = "amount"
        total += row[missing_field]
    return total

total_amount(records)
"""


def feedback_json(response):
    return json.dumps(response, ensure_ascii=False, separators=(",", ":"))


def clean_turn(step, fixture, audit):
    """Run inside a fresh stdlib Python interpreter, returning only this turn's feedback."""
    scope = {}
    exec(LOAD.format(fixture=fixture, audit=audit), scope)
    output = StringIO()
    failure = None
    with redirect_stdout(output):
        if step == 1:
            exec(LOADED, scope)
        else:
            try:
                exec(compile(FAIL, "<diagnostic>", "exec"), scope)
            except KeyError as exc:
                frames = []
                tb = exc.__traceback__.tb_next  # Skip this runner's exec frame.
                while tb is not None:
                    index = len(frames)
                    frame = tb.tb_frame
                    frames.append({
                        "index": index,
                        "file": frame.f_code.co_filename,
                        "line": tb.tb_lineno,
                        "function": frame.f_code.co_name,
                    })
                    tb = tb.tb_next
                if step == 3:
                    local = frame.f_locals
                    return {
                        "values": {name: local[name] for name in NAMES if name in local},
                        "missing": [name for name in NAMES if name not in local],
                        "frame": index,
                    }
                failure = {"type": type(exc).__name__, "message": str(exc)[:160], "frames": frames}
    return {
        "status": "error" if failure else "ok",
        "output": output.getvalue(),
        "truncated": False,
        "failure": failure,
    }


def run_clean(fixture, audit):
    # Only the parent imports Session; each baseline turn starts stdlib Python.
    script = str(Path(__file__).resolve())
    responses = []
    start = perf_counter()
    for step in (1, 2, 3):
        process = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", script, "_worker",
             str(step), str(fixture), str(audit)],
            check=True, capture_output=True, encoding="utf-8", timeout=30,
        )
        responses.append(json.loads(process.stdout))
        if step == 1:
            first = perf_counter() - start
    return responses, first, perf_counter() - start


def failure_frame(response):
    failure = response.get("failure")
    if (response.get("status") != "error" or response.get("truncated")
            or not failure or not failure.get("frames")):
        raise RuntimeError(f"Expected a failure with a frame, got {response!r}")
    return failure["frames"][-1]["index"]


def run_session(session_type, fixture, audit):
    start = perf_counter()
    with session_type() as session:
        loaded = session.execute(LOAD.format(fixture=str(fixture), audit=str(audit)) + LOADED)
        first = perf_counter() - start
        failed = session.execute(FAIL)
        inspected = session.inspect(*NAMES, frame=failure_frame(failed))
    return (loaded, failed, inspected), first, perf_counter() - start


def diagnosis(responses, rows):
    loaded, failed, inspected = responses
    if (loaded.get("status") != "ok" or loaded.get("truncated")
            or loaded.get("failure") is not None
            or loaded.get("output") != f"loaded {rows} records\n"):
        raise RuntimeError(f"Fixture load was not confirmed: {loaded!r}")
    index = failure_frame(failed)
    if inspected.get("frame") != index or inspected.get("missing") != []:
        raise RuntimeError(f"Failure locals were not confirmed: {inspected!r}")
    values = inspected["values"]
    if set(values) != set(NAMES):
        raise RuntimeError(f"Unexpected failure locals: {values!r}")
    return {"error": failed["failure"]["type"], **values}


def make_fixture(path, rows, trial):
    rng = random.Random(trial)
    records = [{"id": f"order-{i:06d}", "amount": rng.randrange(1, 1000)} for i in range(rows)]
    selected = rng.randrange(rows)
    broken = records[selected]
    # Derive the oracle from the difference between the intact and damaged record.
    intact = broken.copy()
    del broken["amount"]
    field, = intact.keys() - broken.keys()
    path.write_text(feedback_json(records), encoding="utf-8")
    return {"error": KeyError.__name__, "record_id": intact["id"], "missing_field": field}


def positive_int(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=positive_int, default=10_000, help="records per fixture")
    parser.add_argument("--repeat", type=positive_int, default=1, help="paired trials")
    args = parser.parse_args()

    from shellless_ops_session import Session

    print("Three turns: load a JSON file → fail while totaling → inspect two failure locals")
    print("First/total are wall-clock ms; both include cold startup, total includes teardown.")
    print("Loads count recorded successful fixture reads (the audit append is timed).")
    print("Feedback = UTF-8 bytes of compact JSON for three returned responses, not tokens")
    print("or wire bytes. Frame metadata can differ; neither path dumps the whole traceback/namespace.")
    with TemporaryDirectory(prefix="ai-session-benchmark-") as directory:
        root = Path(directory)
        for trial in range(args.repeat):
            fixture = root / f"records-{trial}.json"
            expected = make_fixture(fixture, args.rows, trial)
            runners = [
                ("session", lambda fixture, audit: run_session(Session, fixture, audit)),
                ("fresh-python", run_clean),
            ]
            if trial % 2:
                runners.reverse()
            results = []
            for name, runner in runners:
                audit = root / f"{name}-{trial}.loads"
                responses, first, total = runner(fixture, audit)
                conclusion = diagnosis(responses, args.rows)
                if conclusion != expected:
                    raise RuntimeError(f"{name}: got {conclusion!r}, expected {expected!r}")
                loads = len(audit.read_bytes().splitlines())
                feedback = sum(len(feedback_json(reply).encode("utf-8")) for reply in responses)
                results.append((name, first, total, loads, feedback))
            print(f"\nTrial {trial + 1}: both confirmed {feedback_json(expected)}")
            for name, first, total, loads, feedback in sorted(results, reverse=True):
                print(f"  {name:12} first={first * 1000:8.1f} ms  total={total * 1000:8.1f} ms"
                      f"  loads={loads}  feedback={feedback} B")
    print("\nScope: local trusted, deterministic Python; OS file caches are not cleared.")
    print("Fixture creation and benchmark-driver imports are excluded. Session includes Jupyter")
    print("kernel startup; fresh Python uses no kernel and replays setup and failure as needed.")
    print("This measures one cold three-turn task, not an already warm session or a batched,")
    print("cached, or side-effecting workflow.")


if __name__ == "__main__":
    if sys.argv[1:2] == ["_worker"]:
        print(feedback_json(clean_turn(int(sys.argv[2]), *sys.argv[3:])))
    else:
        main()
