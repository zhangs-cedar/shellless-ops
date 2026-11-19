# shellless-ops

Repeatable file and process operations without maintaining separate Bash and PowerShell scripts. Built for Python 3.11+ with no runtime dependencies. Use the Python API for scripts, or pass an argument array to the CLI from task runners.

## Install

Before the first PyPI release, install from a local checkout:

```text
python -m pip install .
```

## Example

```python
import sys

from shellless_ops import find_files, mkdir, run, write_text

out = mkdir("build reports")
write_text(out / "summary.txt", "ready\n")
files = find_files(out, "*.txt")
result = run([sys.executable, "--version"], cwd=out, timeout=10)
print(files, result.stdout.strip())
```

```text
shellless-ops mkdir "build reports"
shellless-ops write "build reports/summary.txt" "ready"
shellless-ops copy "build reports/summary.txt" "build reports/backup.txt"
shellless-ops find "build reports" --pattern "*.txt"
shellless-ops read "build reports/summary.txt"
shellless-ops run --timeout 10 -- python --version
```

`python -m shellless_ops` also works. A task runner with an argument-array API can use `["python", "-m", "shellless_ops", "find", "build reports", "--pattern", "*.txt"]`. A command typed into a terminal is still parsed by that terminal's shell; quote paths with spaces and wildcard patterns at that boundary.

## Behavior

| API | Contract |
| --- | --- |
| `mkdir(path)` | Create missing parents, accept an existing directory and return its `Path`. |
| `read_text(path)` / `write_text(path, text)` | Default to UTF-8 and preserve line endings. Writing replaces existing contents, requires an existing parent directory and returns the `Path`. CLI `read` emits UTF-8 bytes. |
| `copy_file(source, target)` | Copy the contents to an exact destination and return its `Path`. Reject an existing destination. Metadata is not copied. An interrupted copy can leave a partial destination. |
| `find_files(root, pattern="*")` | Recursively match file basenames, including dotfiles, with case-sensitive glob matching. Return paths sorted by their `/`-separated relative names. Skip file symlinks and do not descend into directory symlinks or nested Windows directory reparse points. CLI `find` emits a JSON array of paths with `/` separators. |
| `run(argv, *, cwd=None, timeout=None, check=True, capture=True, encoding="utf-8")` | Pass the executable and each argument separately in a non-empty list or tuple. Return `subprocess.CompletedProcess`. By default, capture output as UTF-8 text and raise `CalledProcessError` on a nonzero exit. Set `encoding=None` for bytes or `capture=False` to inherit output. CLI `run` inherits output and propagates exit status; it uses 124 on timeout and `128 + signal` for signal exits on POSIX. |

`run` does not expand variables, implement pipelines or redirection, or support Windows `.bat` and `.cmd` entry points. It uses the operating system's executable lookup rules; pass an absolute executable path to select a specific installation. A timeout targets the directly launched process, not its entire process tree. Choose the executable and its options as trusted configuration: shell-free launching is not a sandbox for the program being run.

Run tests from the checkout after installing: `python -m unittest discover -s tests -v`.
