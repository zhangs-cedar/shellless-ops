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
shellless-ops search "build reports" "ready" --pattern "*.txt" --limit 5
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
| `search_text(root, query, *, pattern="*", limit=50, max_line_chars=240, max_files=1000, encoding="utf-8-sig")` | 搜索单文件或目录，按路径和行号返回区分大小写的字面命中。`pattern` 只筛目录内的文件名。默认读取 UTF-8（含 BOM）；CLI `search` 输出 UTF-8 JSON。 |
| `run(argv, *, cwd=None, timeout=None, check=True, capture=True, encoding="utf-8")` | 用非空列表或元组分别传入程序和参数，返回 `subprocess.CompletedProcess`。默认按 UTF-8 捕获输出，非零退出抛出 `CalledProcessError`。`encoding=None` 返回字节，`capture=False` 继承输出。CLI `run` 继承输出并传递退出码，超时为 124，POSIX 信号终止为 `128 + 信号编号`。 |

`run` 不做变量展开、管道或重定向，不支持 Windows `.bat` 和 `.cmd`。程序查找遵循操作系统规则；要指定某个安装，传可执行文件的绝对路径。超时针对直接启动的子进程，不承诺回收整棵进程树。不经 Shell 启动不等于沙箱，只运行可信的程序和参数。

### 给 agent 的搜索结果

`search_text` 和 `search` 使用同一结果结构：

```json
{"matches":[{"path":"build reports/summary.txt","line":1,"text":"ready","text_truncated":false}],"truncated":false,"scan_limited":false,"skipped_decode":0}
```

- `line` 从 1 开始。一行命中多次也只返回一条，以首次命中定位预览。
- `text_truncated` 表示预览被裁剪；`truncated` 表示已找到额外命中但没放进结果。精确凑满上限不算截断。
- 搜索目录默认跳过后代路径中的 `.git`、`.hg`、`.svn` 和 `.venv`。遇到解码失败的文件时丢弃该文件已收集的命中，累加 `skipped_decode` 后继续；显式搜索单文件时仍报错。缺路径或打开失败不会作为零命中返回。
- `--max-files` 限制最多打开多少个候选文件。发现尚未打开的候选文件时，`scan_limited` 为 `true`；这不代表后续一定有命中。遇到额外命中提前结束时，不会继续检查后续文件。文件数不是用时或单行内存上限。大仓库优先传更小的根目录或 `--pattern "*.py"`。

## 失败证据

给 agent 一份小报告，而不是把完整 traceback 和源码塞进同一个响应：

```text
shellless-ops evidence --output failure.json --var amount --source-root . -- script.py
```

命令保留脚本原本的输出和退出行为，未处理的异常仍打印 traceback（含运行器帧）。报告单独写入新建的 JSON 文件，不覆盖旧文件。agent 可以只读取报告，需要时再看进程输出。报告默认记录解释器、脚本路径和工作目录；脚本参数默认不记录，确认无敏感信息后可用 `--record-args`。`--code-version` 是调用方给出的复现提示，不证明内容与 Git 提交完全一致。

```python
from shellless_ops.evidence import capture

with capture(names=("amount",)) as report:
    run_the_operation()
```

由原调用方处理异常，异常仍会传播；捕获后从 `report["failure"]` 读取证据。报告只包含最近 8 帧、失败帧中显式指定的变量和可选的 5 行源码。默认不读源码、不记录异常消息或环境变量，不调用对象的 `repr` 或 `__summary__`。若生成证据本身失败，报告用 `capture_error` 标记。这只观察当前 Python 进程里未处理的 `Exception`，不会分析子进程、已被业务处理的异常或 `SystemExit`。源码是捕获时磁盘上的文本。只选适合分享的变量和文件，报告不做脱敏。

## 贡献

欢迎提交 [Issue](https://github.com/zhangs-cedar/shellless-ops/issues) 或 Pull Request。在仓库目录执行 `python -m pip install .` 安装当前代码，再运行 `python -m unittest discover -s tests -v`。

想试用常驻 Python 内核、按需读取失败现场和多 agent 独立会话，见 [AI 调试会话实验](experiments/ai-session/README.md)。它不属于基础库的发行包。
