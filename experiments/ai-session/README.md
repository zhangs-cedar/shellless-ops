# AI 调试会话（实验）

让 AI 在本地保留 Python 的运行现场，只取回定位问题所需的证据。这个原型独立于 `shellless-ops` 首发包，不从 PyPI 安装。

## 快速开始

在本实验目录执行：

```text
python -m pip install .
python -m unittest discover -s tests -v
```

```python
from shellless_ops_session import Session

with Session() as session:
    report = session.execute(
        "def parse():\n    amount = '100'\n    return amount - 10\nparse()"
    )
    frame = report["failure"]["frames"][-1]["index"]
    evidence = session.inspect("amount", frame=frame)
    print(evidence["values"])
```

`execute` 执行下一段代码，保留会话变量；`inspect` 查指定名称，不返回整个命名空间；`reset` 丢弃内核。失败帧只对当前现场有效，下一次执行或重置后不要继续用旧索引。超时会丢弃当前内核，下次调用重新启动。输出截断限制的是返回字符数，不是模型 token，也不是内核资源上限。

## 接到 AI 客户端

在实验目录执行 `python -m pip install ".[mcp]"`。在可信项目的工作目录启动本地 stdio 服务。以下是客户端需要传递的命令，字段名按客户端配置：

```json
{
  "command": "/absolute/path/to/venv/bin/python",
  "args": ["-m", "shellless_ops_session.mcp_server"]
}
```

工具为 `execute(session_id, code)`、`inspect(session_id, names, frame)` 和 `reset(session_id)`。`frame` 可省略，表示查会话变量。结果只有一个包含紧凑 JSON 的文本块，不重复发送。服务进程最多保留四个会话：不同标签可并行，同一标签正在执行时立即返回 `busy`；用完调用 `reset` 释放名额。客户端断开并结束服务后，会话不会继承到新的服务进程。

## 多 agent 协作

给每个 agent 独立会话；交接时传代码版本、复现步骤、必要字段和最终测试命令，不传整个内核。会话用于探索，修复要写入文件，再用干净进程验证。

一个交接示例：

```text
版本：<commit>；任务：定位折扣计算失败
复现：python -m unittest tests.test_discount
证据：parse() 中 amount 为 "100"（字符串），减法触发 TypeError
验收：补充字符串输入用例，在干净进程运行同一测试
```

内核运行本机可信代码，继承本机用户权限。独立会话只隔离 Python 运行状态，不隔离文件、环境变量或网络访问。不要把会话当作权限边界。

## 什么时候用

遇到重复加载代价高、需要多次查看同一个失败现场的任务，再开会话。一次性检查和最终回归直接用干净进程。运行 `python benchmark.py --repeat 2` 查看本机对照，实测范围和限制见 [实验决策](DECISIONS.md)。
