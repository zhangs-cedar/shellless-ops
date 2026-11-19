"""Compare diagnostic feedback for 20 deterministic, injected Python failures.

Run from the repository root: PYTHONPATH=src python benchmarks/compare_evidence.py
Optional --tokenizer uses separately installed tiktoken and a locally cached
cl100k_base vocabulary. This benchmark never fetches that vocabulary.
"""

import argparse
import ast
from dataclasses import dataclass
import json
from pathlib import Path
import platform
import re
from tempfile import TemporaryDirectory
import traceback


@dataclass(frozen=True)
class Fixture:
    label: str
    source: str
    error: type[Exception]
    function: str
    healthy: str | int
    injected: tuple[str | int, ...]
    local: str
    message_prefix: str


FIXTURES = (
    Fixture(
        "missing-field",
        """\
def required_value(row, missing_field):
    record_id = row["id"]
    if missing_field not in row:
        raise KeyError(f"{record_id}: missing field {missing_field!r}")
    return row[missing_field]


def operation(record_id, field):
    row = {"id": record_id, "name": "adapter", "quantity": 3}
    return required_value(row, field)
""",
        KeyError, "required_value", "name",
        ("amount", "currency", "warehouse", "sku", "批次"),
        "missing_field", "missing field",
    ),
    Fixture(
        "invalid-quantity",
        """\
def parse_quantity(row):
    record_id = row["id"]
    raw_quantity = row["quantity"]
    if not raw_quantity.isdecimal():
        raise ValueError(f"{record_id}: invalid quantity {raw_quantity!r}")
    return int(raw_quantity)


def operation(record_id, quantity):
    return parse_quantity({"id": record_id, "quantity": quantity})
""",
        ValueError, "parse_quantity", "12",
        ("?", "4.5", "", "3件", "-2"),
        "raw_quantity", "invalid quantity",
    ),
    Fixture(
        "zero-recipients",
        """\
def split_order(order, divisor):
    record_id = order["id"]
    if divisor == 0:
        raise ZeroDivisionError(f"{record_id}: zero recipient count {divisor}")
    return order["quantity"] / divisor


def operation(record_id, recipients):
    order = {"id": record_id, "quantity": 24}
    return split_order(order, recipients)
""",
        ZeroDivisionError, "split_order", 2, (0, 0, 0, 0, 0),
        "divisor", "zero recipient count",
    ),
    Fixture(
        "invalid-slot",
        """\
def pick_slot(manifest, slot):
    record_id = manifest["id"]
    parcels = manifest["parcels"]
    if not 0 <= slot < len(parcels):
        raise IndexError(f"{record_id}: unavailable slot {slot}")
    return parcels[slot]


def operation(record_id, slot):
    manifest = {"id": record_id, "parcels": ["adapter", "cable", "case"]}
    return pick_slot(manifest, slot)
""",
        IndexError, "pick_slot", 1, (-1, 3, 6, 99, 1000),
        "slot", "unavailable slot",
    ),
)

METHODS = ("traceback+file", "leaf-traceback", "evidence-json")
REPOSITORY = Path(__file__).resolve().parents[1]
FRAME = re.compile(r'^  File "([^"\n]+)", line (\d+), in ([^\n]+)$', re.MULTILINE)
SOURCE_HEADER = "\n--- Leaf source file ---\n"
TOKENIZER = "cl100k_base"


@dataclass(frozen=True)
class Diagnosis:
    error: str
    path: str
    line: int
    function: str
    statement: str
    values: dict


def display_path(raw, root):
    """Replace machine-specific directory prefixes; don't drop any frames."""
    path = Path(raw)
    if not path.is_absolute():
        if (root / path).is_file():
            path = root / path
        else:
            return raw
    for prefix, label in ((root, "fixtures"), (REPOSITORY, "repo")):
        if path.is_relative_to(prefix):
            return f"{label}/{path.relative_to(prefix).as_posix()}"
    return raw


def traceback_payloads(operation, record_id, injected, root):
    def formatted(error, limit):
        text = "".join(traceback.format_exception(error, limit=limit))
        return FRAME.sub(
            lambda frame: f'  File "{display_path(frame[1], root)}", '
                          f"line {frame[2]}, in {frame[3]}",
            text,
        )

    try:
        operation(record_id, injected)
    except Exception as error:
        leaf = traceback.extract_tb(error.__traceback__, limit=-1)[-1]
        source = Path(leaf.filename).read_text(encoding="utf-8")
        return (
            formatted(error, limit=None) + SOURCE_HEADER + source,
            formatted(error, limit=-1),
        )
    raise RuntimeError(f"{record_id}: baseline operation did not fail")


def evidence_payload(capture, operation, fixture, record_id, injected, root):
    try:
        with capture(names=("record_id", fixture.local), source_root=root) as report:
            operation(record_id, injected)
    except fixture.error:
        pass
    else:
        raise RuntimeError(f"{record_id}: capture did not propagate the injected failure")

    # Serialize the entire returned report, changing only machine-specific paths.
    failure = report["failure"]
    normalized = {
        **failure,
        "frames": [
            {**frame, "path": display_path(frame["path"], root)}
            for frame in failure["frames"]
        ],
    }
    return json.dumps(
        {**report, "failure": normalized}, ensure_ascii=False, separators=(",", ":")
    )


def traceback_diagnosis(payload, fixture, *, with_file):
    if with_file:
        payload, _, file_source = payload.partition(SOURCE_HEADER)
    leaf = list(FRAME.finditer(payload))[-1]
    path, line, function = leaf.groups()
    line = int(line)
    statement = payload[leaf.end() + 1:].splitlines()[0].strip()
    if with_file and file_source.splitlines()[line - 1].strip() != statement:
        raise RuntimeError("Traceback statement disagrees with the supplied source file")
    error, _, message = payload.splitlines()[-1].partition(": ")
    if error == "KeyError":
        message = ast.literal_eval(message)  # Python displays the KeyError argument with repr.
    record_id, detail = re.fullmatch(
        rf"([^:]+): {re.escape(fixture.message_prefix)} (.+)", message
    ).groups()
    values = {"record_id": record_id, fixture.local: ast.literal_eval(detail)}
    return Diagnosis(error, path, line, function, statement, values)


def evidence_diagnosis(payload):
    failure = json.loads(payload)["failure"]
    leaf = failure["frames"][-1]
    statement, = (
        entry["text"].strip()
        for entry in (failure["source"] or ())
        if entry["line"] == leaf["line"]
    )
    return Diagnosis(
        failure["type"], leaf["path"], leaf["line"], leaf["function"],
        statement, failure["values"],
    )


def compare(capture, fixture, index, injected, root):
    record_id = f"{fixture.label}-{index}-订单"
    path = root / f"{fixture.label}-{index}.py"
    path.write_text(fixture.source, encoding="utf-8", newline="\n")
    scope = {}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), scope)
    operation = scope["operation"]
    operation(record_id, fixture.healthy)

    # The oracle comes from the planned mutation and the declared raise site,
    # not from either execution's traceback or locals.
    line, = (
        lineno for lineno, text in enumerate(fixture.source.splitlines(), 1)
        if text.lstrip().startswith(f"raise {fixture.error.__name__}(")
    )
    expected = Diagnosis(
        fixture.error.__name__, f"fixtures/{path.name}", line, fixture.function,
        fixture.source.splitlines()[line - 1].strip(),
        {"record_id": record_id, fixture.local: injected},
    )

    full, compact = traceback_payloads(operation, record_id, injected, root)
    evidence = evidence_payload(capture, operation, fixture, record_id, injected, root)
    payloads = full, compact, evidence
    for method, payload, decode in zip(
        METHODS, payloads,
        (
            lambda text: traceback_diagnosis(text, fixture, with_file=True),
            lambda text: traceback_diagnosis(text, fixture, with_file=False),
            evidence_diagnosis,
        ),
    ):
        try:
            actual = decode(payload)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as error:
            raise RuntimeError(f"{record_id}: cannot decode {method} feedback") from error
        if actual != expected or type(actual.values[fixture.local]) is not type(injected):
            raise RuntimeError(f"{record_id}: {method} gave {actual!r}, expected {expected!r}")
    return payloads


def token_counter(parser):
    from unittest.mock import patch

    try:
        import tiktoken
        import tiktoken.load
    except ImportError:
        parser.error("--tokenizer requires separately installed tiktoken")
    # tiktoken can normally fetch a missing vocabulary. Allow a cache hit only.
    try:
        with patch.object(
            tiktoken.load, "read_file",
            side_effect=OSError(f"{TOKENIZER} vocabulary is not in the local tiktoken cache"),
        ):
            encoding = tiktoken.get_encoding(TOKENIZER)
    except OSError as error:
        parser.error(str(error))
    return lambda text: len(encoding.encode_ordinary(text))


def print_totals(label, totals):
    print(f"\n{label} (sum of individual feedback payloads)")
    print(f"{'fixture group':<20}" + "".join(f"{method:>17}" for method in METHODS))
    for group, sizes in totals.items():
        print(f"{group:<20}" + "".join(f"{size:17d}" for size in sizes))
    print(f"{'total':<20}" + "".join(f"{sum(sizes):17d}" for sizes in zip(*totals.values())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tokenizer", action="store_true",
        help=f"also count {TOKENIZER} tokens using separately installed tiktoken (local cache only)",
    )
    args = parser.parse_args()
    count_tokens = token_counter(parser) if args.tokenizer else None

    from shellless_ops.evidence import capture

    byte_totals = {}
    token_totals = {}
    with TemporaryDirectory(prefix="compare-evidence-") as directory:
        root = Path(directory).resolve()
        for fixture in FIXTURES:
            byte_totals[fixture.label] = byte_sizes = [0] * len(METHODS)
            token_totals[fixture.label] = token_sizes = [0] * len(METHODS)
            for index, injected in enumerate(fixture.injected, 1):
                for column, payload in enumerate(compare(capture, fixture, index, injected, root)):
                    byte_sizes[column] += len(payload.encode("utf-8"))
                    if count_tokens is not None:
                        token_sizes[column] += count_tokens(payload)

    count = sum(len(fixture.injected) for fixture in FIXTURES)
    print(f"Python {platform.python_version()}: verified location and facts for {count} injected failures.")
    print("traceback+file: full Python traceback and entire leaf source file.")
    print("leaf-traceback: Python traceback limited to the last frame (includes its source line).")
    print("evidence-json: complete capture report, serialized as compact JSON.")
    print("These fixture exceptions include the diagnostic values in their messages,")
    print("so even the leaf-only baseline can recover those values without a locals dump.")
    print("Fixture and repository path prefixes are normalized. No model is called;")
    print("these sizes are not agent token usage or a measure of debugging success.")
    print_totals("UTF-8 bytes", byte_totals)
    if count_tokens is not None:
        print_totals(f"{TOKENIZER} tokens", token_totals)


if __name__ == "__main__":
    main()
