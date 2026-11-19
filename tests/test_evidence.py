import json
import subprocess
import sys
import tempfile
import traceback
import unittest
from pathlib import Path

from shellless_ops.evidence import capture


class EvidenceTests(unittest.TestCase):
    def test_capture_keeps_original_exception_and_only_named_locals(self):
        class Object:
            def __repr__(self):
                raise AssertionError("repr called")

            def __summary__(self):
                raise AssertionError("summary hook called")

        error = ValueError("message is not in the evidence")

        def fail():
            amount = "100"
            obj = Object()
            private = "do not collect"
            observations = list(range(500))
            raise error

        try:
            with capture(names=("amount", "obj", "observations", "typo")) as report:
                fail()
        except ValueError as received:
            self.assertIs(received, error)
            self.assertEqual(traceback.extract_tb(received.__traceback__)[-1].name, "fail")
        else:
            self.fail("capture suppressed the exception")
        failure = report["failure"]
        self.assertEqual(failure["type"], "ValueError")
        self.assertEqual(failure["frames"][-1]["function"], "fail")
        self.assertEqual(failure["values"], {
            "amount": "100", "obj": {"type": "Object"}, "observations": {"type": "list", "length": 500}
        })
        self.assertEqual(failure["missing"], ["typo"])
        self.assertIsNone(failure["source"])
        self.assertNotIn("do not collect", json.dumps(report))
        with capture() as normal:
            self.assertEqual(2 + 2, 4)
        self.assertEqual(normal, {"failure": None})

    def test_source_is_opt_in_and_runtime_frames_are_bounded(self):
        def recurse(depth):
            if depth:
                return recurse(depth - 1)
            raise RuntimeError()

        with self.assertRaises(RuntimeError):
            with capture(source_root=Path(__file__).parent) as report:
                recurse(20)
        failure = report["failure"]
        self.assertEqual(len(failure["frames"]), 8)
        line = failure["frames"][-1]["line"]
        self.assertIn({"line": line, "text": "            raise RuntimeError()"}, failure["source"])
        with tempfile.TemporaryDirectory() as another_root, self.assertRaises(RuntimeError):
            with capture(source_root=another_root) as elsewhere:
                recurse(0)
        self.assertIsNone(elsewhere["failure"]["source"])

    def test_evidence_cli_writes_separate_report_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "例子 程序.py"
            output = root / "证据.json"
            script.write_text(
                "import sys\nprint(sys.argv[1])\nvalue = 7\nraise RuntimeError('failed')\n",
                encoding="utf-8",
            )
            command = [
                sys.executable, "-m", "shellless_ops", "evidence", "--output", str(output),
                "--var", "value", "--source-root", directory, "--code-version", "rev-123",
                "--", str(script), "argument-not-recorded",
            ]
            result = subprocess.run(command, capture_output=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout.splitlines(), [b"argument-not-recorded"])
            self.assertIn(b"RuntimeError: failed", result.stderr)
            evidence = output.read_text(encoding="utf-8")
            report = json.loads(evidence)
            self.assertEqual(report["failure"]["values"], {"value": 7})
            self.assertEqual(report["failure"]["frames"][-1]["line"], 4)
            self.assertEqual(report["repro"]["code_version"], "rev-123")
            self.assertEqual(report["repro"]["omitted_args"], 1)
            self.assertNotIn("argument-not-recorded", evidence)
            repeated = subprocess.run(command, capture_output=True)
            self.assertEqual(repeated.returncode, 1)
            self.assertEqual(repeated.stdout, b"")
            self.assertEqual(output.read_text(encoding="utf-8"), evidence)
