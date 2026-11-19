import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shellless_ops import copy_file, find_files, mkdir, read_text, run, write_text


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
