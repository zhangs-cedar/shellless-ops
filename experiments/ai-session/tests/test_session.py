import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from shellless_ops_session import Session


class SessionStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = cls.enterClassContext(Session(timeout=3))

    def test_state_carries_over_until_reset(self):
        first = self.session.execute("counter = 40")
        self.assertEqual(first["status"], "ok", first)
        self.assertIsNone(first["failure"])
        second = self.session.execute("counter += 2\nprint(counter)")
        self.assertEqual(second["status"], "ok", second)
        self.assertEqual(second["output"], "42\n")
        self.assertEqual(
            self.session.inspect("counter", "unknown"),
            {"values": {"counter": 42}, "missing": ["unknown"], "frame": None},
        )

        self.session.reset()
        self.assertEqual(
            self.session.inspect("counter"),
            {"values": {}, "missing": ["counter"], "frame": None},
        )

    def test_failure_preserves_user_frames_and_local_values(self):
        seeded = self.session.execute("attempts = 0")
        self.assertEqual(seeded["status"], "ok", seeded)
        result = self.session.execute(
            "def outer():\n"
            "    inner()\n"
            "def inner():\n"
            "    global attempts\n"
            "    attempts += 1\n"
            "    local_value = 'from inner'\n"
            "    raise ValueError('test failure')\n"
            "outer()\n"
        )
        self.assertEqual(result["status"], "error", result)
        failure = result["failure"]
        self.assertEqual(failure["type"], "ValueError")
        self.assertEqual(failure["message"], "test failure")
        self.assertEqual(len(failure["frames"]), 3)
        user_frames = [
            frame
            for frame in failure["frames"]
            if frame["function"] in {"outer", "inner"}
        ]
        self.assertCountEqual(
            [(frame["function"], frame["line"]) for frame in user_frames],
            [("outer", 2), ("inner", 7)],
        )
        for frame in user_frames:
            self.assertIsInstance(frame["index"], int)
            self.assertIsInstance(frame["file"], str)
            self.assertTrue(frame["file"])
        inner_index = next(
            frame["index"] for frame in user_frames if frame["function"] == "inner"
        )
        self.assertEqual(
            self.session.inspect("local_value", frame=inner_index),
            {
                "values": {"local_value": "from inner"},
                "missing": [],
                "frame": inner_index,
            },
        )
        self.assertEqual(self.session.inspect("attempts")["values"], {"attempts": 1})

        invalid = self.session.execute("def broken(:")
        self.assertEqual(invalid["failure"]["type"], "SyntaxError")
        self.assertEqual(invalid["failure"]["frames"], [])
        with self.assertRaisesRegex(ValueError, "Kernel inspection failed"):
            self.session.inspect("local_value", frame=inner_index)

    def test_inspect_limits_previews_without_calling_custom_repr(self):
        seeded = self.session.execute(
            "class Unprintable:\n"
            "    def __repr__(self):\n"
            "        raise RuntimeError('repr should not run')\n"
            "obj = Unprintable()\n"
            "large = 'x' * 1000"
        )
        self.assertEqual(seeded["status"], "ok", seeded)
        values = self.session.inspect("obj", "large")["values"]
        self.assertEqual(values["obj"], {"type": "Unprintable"})
        self.assertEqual(values["large"], {"type": "str", "value": "x" * 80, "length": 1000})
        with self.assertRaisesRegex(ValueError, "identifiers"):
            self.session.inspect("obj.__repr__()")


class SessionIsolationTests(unittest.TestCase):
    def test_parallel_sessions_keep_separate_namespaces(self):
        ready = Barrier(2, timeout=10)
        inspected = Barrier(2, timeout=10)
        reset_done = Barrier(2, timeout=10)

        def run(value, own_name, other_name):
            with Session(timeout=3) as session:
                assigned = session.execute(f"shared = {value}\n{own_name} = shared")
                self.assertEqual(assigned["status"], "ok", assigned)
                ready.wait()
                before = session.inspect("shared", own_name, other_name)
                inspected.wait()
                if own_name == "only_left":
                    session.reset()
                reset_done.wait()
                return before, session.inspect("shared")

        with ThreadPoolExecutor(max_workers=2) as pool:
            left = pool.submit(run, 11, "only_left", "only_right")
            right = pool.submit(run, 22, "only_right", "only_left")
            left_before, left_after = left.result()
            right_before, right_after = right.result()
            self.assertEqual(
                left_before,
                {
                    "values": {"shared": 11, "only_left": 11},
                    "missing": ["only_right"],
                    "frame": None,
                },
            )
            self.assertEqual(
                right_before,
                {
                    "values": {"shared": 22, "only_right": 22},
                    "missing": ["only_left"],
                    "frame": None,
                },
            )
            self.assertEqual(
                left_after, {"values": {}, "missing": ["shared"], "frame": None}
            )
            self.assertEqual(
                right_after, {"values": {"shared": 22}, "missing": [], "frame": None}
            )

    def test_output_cap_reports_truncation_only_when_needed(self):
        limit = 64
        with Session(timeout=3, max_output=limit) as session:
            short = session.execute("print('short')")
            self.assertEqual(short["status"], "ok", short)
            self.assertEqual(short["output"], "short\n")
            self.assertIs(short["truncated"], False)

            long = session.execute("print('x' * 4096)")
            self.assertEqual(long["status"], "ok", long)
            self.assertIsInstance(long["output"], str)
            self.assertLessEqual(len(long["output"]), limit)
            self.assertTrue(long["output"].startswith("x"))
            self.assertIs(long["truncated"], True)

    def test_timeout_discards_namespace_and_next_execution_succeeds(self):
        with Session(timeout=1) as session:
            seeded = session.execute("before_timeout = 17")
            self.assertEqual(seeded["status"], "ok", seeded)
            timed_out = session.execute(
                "import time\n"
                "during_timeout = 18\n"
                "time.sleep(10)\n"
            )
            self.assertEqual(timed_out["status"], "timeout", timed_out)

            recovered = session.execute(
                "assert 'before_timeout' not in globals()\n"
                "assert 'during_timeout' not in globals()\n"
                "after_timeout = 23\n"
                "print(after_timeout)\n"
            )
            self.assertEqual(recovered["status"], "ok", recovered)
            self.assertEqual(recovered["output"], "23\n")
            self.assertEqual(
                session.inspect("after_timeout"),
                {"values": {"after_timeout": 23}, "missing": [], "frame": None},
            )


if __name__ == "__main__":
    unittest.main()
