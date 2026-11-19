import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shellless_ops import copy_file, find_files, mkdir, read_text, run, search_text, write_text


class ShelllessOpsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "测试 空格"

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "shellless_ops", *args], capture_output=True, check=False
        )

    def test_cli_file_workflow(self):
        source = self.root / "源 文档.txt"
        target = self.root / "副本.txt"
        text = "第一行\r\n第二行\n"
        for args in [("mkdir", self.root), ("write", source, text), ("copy", source, target)]:
            result = self.cli(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
        result = self.cli("find", self.root, "--pattern", "*.txt")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [target.as_posix(), source.as_posix()])
        result = self.cli("read", target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, text.encode("utf-8"))

    def test_search_distinguishes_missing_and_empty(self):
        with self.assertRaises(FileNotFoundError):
            find_files(self.root)
        self.assertEqual(find_files(mkdir(self.root)), [])
        lower = write_text(mkdir(self.root / "a") / "a.txt", "")
        write_text(self.root / "b.TXT", "")
        self.assertEqual(find_files(self.root, "*.txt"), [lower])

    def test_search_text_cli_and_api_return_numbered_literal_previews(self):
        file = mkdir(self.root) / "配置 日志.txt"
        query = "失败[1]"
        write_text(file, f"{query}\r\n失败1\r\n{'x' * 30_000}{query}后续\r\n", encoding="utf-8-sig")
        (self.root / "binary.dat").write_bytes(b"\xff")
        expected = {
            "matches": [
                {"path": file.as_posix(), "line": 1, "text": query, "text_truncated": False},
                {"path": file.as_posix(), "line": 3, "text": "xxxxx失败[1]后续", "text_truncated": True},
            ],
            "truncated": False,
            "scan_limited": False,
            "skipped_decode": 0,
        }
        self.assertEqual(
            search_text(self.root, query, pattern="*.txt", limit=2, max_line_chars=12),
            expected,
        )
        result = self.cli(
            "search", self.root, query, "--pattern", "*.txt", "--limit", "2", "--max-line-chars", "12"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(query.encode("utf-8"), result.stdout)
        self.assertEqual(json.loads(result.stdout), expected)

    def test_search_text_limit_and_order(self):
        later = write_text(mkdir(self.root) / "z.txt", "needle\n")
        earlier = write_text(mkdir(self.root / "a") / "first.txt", "needle needle\nneedle\n")
        result = search_text(self.root, "needle", limit=2)
        self.assertTrue(result["truncated"])
        self.assertEqual(
            [(hit["path"], hit["line"]) for hit in result["matches"]],
            [(earlier.as_posix(), 1), (earlier.as_posix(), 2)],
        )
        self.assertEqual(
            search_text(later, "missing"),
            {"matches": [], "truncated": False, "scan_limited": False, "skipped_decode": 0},
        )

    def test_search_text_reports_missing_and_decode_errors(self):
        with self.assertRaises(FileNotFoundError):
            search_text(self.root, "needle")
        bad = mkdir(self.root) / "wrong.txt"
        bad.write_bytes(b"\xffneedle")
        with self.assertRaisesRegex(ValueError, "wrong.txt"):
            search_text(bad, "needle")
        self.assertEqual(search_text(bad, "needle", encoding="latin-1")["matches"][0]["line"], 1)
        result = self.cli("search", bad, "needle")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"wrong.txt", result.stderr)

    def test_search_repository_skips_default_exclusions_and_counts_decode_errors(self):
        write_text(mkdir(self.root / ".git") / "config", "needle")
        write_text(mkdir(self.root / ".venv") / "artifact.txt", "needle")
        bad = self.root / "a.bin"
        bad.write_bytes(b"needle\n" + b"x\n" * 5_000 + b"\xff")
        visible = write_text(mkdir(self.root / ".source") / "源 文件.txt", "needle")
        result = self.cli("search", self.root, "needle")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["skipped_decode"], 1)
        self.assertEqual([hit["path"] for hit in report["matches"]], [visible.as_posix()])
        self.assertFalse(report["scan_limited"])
        self.assertEqual(len(find_files(self.root)), 4)

    def test_search_text_scan_budget_is_distinct_from_match_limit(self):
        write_text(mkdir(self.root) / "a.txt", "needle\n")
        write_text(self.root / "b.txt", "needle\n")
        report = search_text(self.root, "needle", limit=1, max_files=1)
        self.assertEqual(len(report["matches"]), 1)
        self.assertTrue(report["scan_limited"])
        self.assertFalse(report["truncated"])
        cli = self.cli("search", self.root, "needle", "--limit", "1", "--max-files", "1")
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout), report)
        for key, value in (("limit", 2.5), ("max_files", True), ("max_line_chars", 0)):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, key):
                    search_text(self.root, "needle", **{key: value})
        self.assertEqual(self.cli("search", self.root, "needle", "--max-files", "0").returncode, 1)

    def test_search_can_stop_before_descending_into_later_directories(self):
        file = write_text(mkdir(self.root) / "a.txt", "needle\nneedle\n")
        nested = mkdir(self.root / "a")
        child = write_text(nested / "file.txt", "needle\n")
        with patch("shellless_ops.os.scandir", wraps=os.scandir) as scandir:
            result = search_text(self.root, "needle", limit=1)
        self.assertTrue(result["truncated"])
        scandir.assert_called_once_with(self.root)
        self.assertEqual(find_files(self.root), [file, child])

    @unittest.skipIf(os.name == "nt", "symlink creation can require privileges on Windows")
    def test_find_skips_symbolic_links(self):
        mkdir(self.root)
        file = write_text(self.root / "real.txt", "")
        (self.root / "alias.txt").symlink_to(file)
        (self.root / "loop").symlink_to(self.root, target_is_directory=True)
        self.assertEqual(find_files(self.root, "*.txt"), [file])

    @unittest.skipUnless(os.name == "nt", "Windows directory junction handling")
    def test_find_skips_windows_directory_junction(self):
        file = write_text(mkdir(self.root) / "real.txt", "")
        target = mkdir(self.root.parent / "junction-target")
        write_text(target / "outside.txt", "outside")
        junction = self.root / "junction"
        # Use fixed relative names so cmd never parses the temporary directory path.
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/j", "junction", r"..\junction-target"],
            cwd=self.root,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        self.addCleanup(junction.rmdir)
        self.assertEqual(read_text(junction / "outside.txt"), "outside")
        self.assertEqual(find_files(self.root, "*.txt"), [file])

    def test_copy_does_not_overwrite(self):
        mkdir(self.root)
        source = write_text(self.root / "source", "abc\r\ndef\n")
        target = write_text(self.root / "target", "keep")
        self.assertEqual(read_text(source), "abc\r\ndef\n")
        with self.assertRaises(FileExistsError):
            copy_file(source, target)
        self.assertEqual(read_text(target), "keep")

    def test_run_passes_literal_args_and_cwd(self):
        mkdir(self.root)
        arguments = ['测试 空格 & | "quoted"', "", "ends with space and backslash \\", "--"]
        code = (
            "import json, pathlib, sys; "
            "print(json.dumps([pathlib.Path.cwd().name, sys.argv[1:]]))"
        )
        command = [sys.executable, "-c", code, *arguments]
        expected = [self.root.name, arguments]
        self.assertEqual(json.loads(run(command, cwd=self.root).stdout), expected)
        result = self.cli("run", "--cwd", self.root, "--", *command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), expected)

    def test_run_preserves_failure_and_cli_exit_code(self):
        code = "import sys; print('output'); sys.stderr.write('diagnostic'); sys.exit(7)"
        command = [sys.executable, "-c", code]
        with self.assertRaises(subprocess.CalledProcessError) as failure:
            run(command)
        self.assertEqual(failure.exception.returncode, 7)
        self.assertEqual(failure.exception.stdout, "output\n")
        self.assertEqual(failure.exception.stderr, "diagnostic")
        result = self.cli("run", "--", *command)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [b"output"])
        self.assertEqual(result.stderr, b"diagnostic")

    def test_run_timeout(self):
        command = [sys.executable, "-c", "import time; time.sleep(10)"]
        with self.assertRaises(subprocess.TimeoutExpired):
            run(command, timeout=0.1)
        result = self.cli("run", "--timeout", "0.1", "--", *command)
        self.assertEqual(result.returncode, 124, result.stderr)

    def test_run_rejects_command_strings(self):
        with self.assertRaises(TypeError):
            run("python -V")

    @unittest.skipUnless(os.name == "nt", "Windows batch handling")
    def test_run_rejects_windows_batch_files(self):
        with self.assertRaises(ValueError):
            run(["build.CMD", "argument"])
