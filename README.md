# shellless-ops

`shellless-ops` 是一套跨平台的 Python 文件和进程工具。它统一路径、编码、查找结果和退出码，减少同一任务需要分别维护 Bash 和 PowerShell 版本的情况。要求 Python 3.11+，无运行时依赖。

## 安装

从 [PyPI](https://pypi.org/project/shellless-ops/) 安装：

```text
python -m pip install shellless-ops
```

## 示例

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

也可以用 `python -m shellless_ops`。任务运行器如果支持参数数组，传入 `["python", "-m", "shellless_ops", "find", "build reports", "--pattern", "*.txt"]`，无需拼 Shell 命令字符串。在终端直接键入命令时，仍需按当前 Shell 的规则给含空格的路径和通配模式加引号。

## 接口约定

| API | 行为 |
| --- | --- |
| `mkdir(path)` | 创建缺失的父目录，接受已存在的目录，返回 `Path`。 |
| `read_text(path)` / `write_text(path, text)` | 默认 UTF-8，保留原换行。写入要求父目录已存在，会覆盖原内容并返回 `Path`。CLI `read` 输出 UTF-8 字节。 |
| `copy_file(source, target)` | 复制内容到指定目标文件并返回 `Path`，目标已存在时拒绝覆盖。不复制元数据；写入中断时不清理部分目标文件。 |
| `find_files(root, pattern="*")` | 递归匹配文件名，区分大小写，包含隐藏文件。按使用 `/` 分隔的相对路径排序。跳过文件符号链接，不进入目录符号链接或扫描中遇到的 Windows 目录重解析点。CLI `find` 输出 JSON 路径数组，分隔符统一为 `/`。 |
| `run(argv, *, cwd=None, timeout=None, check=True, capture=True, encoding="utf-8")` | 用非空列表或元组分别传入程序和参数，返回 `subprocess.CompletedProcess`。默认按 UTF-8 捕获输出，非零退出抛出 `CalledProcessError`。`encoding=None` 返回字节，`capture=False` 继承输出。CLI `run` 继承输出并传递退出码，超时为 124，POSIX 信号终止为 `128 + 信号编号`。 |

`run` 不做变量展开、管道或重定向，不支持 Windows `.bat` 和 `.cmd`。程序查找遵循操作系统规则；要指定某个安装，传可执行文件的绝对路径。超时针对直接启动的子进程，不承诺回收整棵进程树。不经 Shell 启动不等于沙箱，只运行可信的程序和参数。

## 贡献

欢迎提交 [Issue](https://github.com/zhangs-cedar/shellless-ops/issues) 或 Pull Request。在仓库目录执行 `python -m pip install .` 安装当前代码，再运行 `python -m unittest discover -s tests -v`。

想试用常驻 Python 内核、按需读取失败现场和多 agent 独立会话，见 [AI 调试会话实验](experiments/ai-session/README.md)。它不属于基础库的发行包。
