# shellless-ops v0.1.0 首发验收

- `python -m unittest discover -s tests -v`：所有用例通过。用临时目录验收 CLI 的建目录、写入、复制、查找和读取；用真实 Python 子进程验收参数边界、工作目录、标准输出、标准错误、非零退出码和超时。
- 文件路径包含中文和空格。文本以 UTF-8 写入，原样保留混合换行。搜索结果按相对路径排序，对文件名区分大小写。找不到根路径时报错，空目录正常返回空结果。
- 成功构建 wheel 和 sdist；包元数据声明 `shellless-ops`、MIT 和 Python 3.11+。从源码目录之外的隔离环境安装构建产物，验证 `shellless-ops --help`、`python -m shellless_ops --help` 和导入。
- macOS、Linux 和 Windows 分别从构建产物安装并运行同一测试套件。Windows 另外核对 `.cmd` / `.bat` 拒绝行为和目录链接边界。没跑过的平台不计为兼容性已验证。
- GitHub 分支的提交哈希与本地一致后才算推送成功。CI 需要读取实际运行结果，不能只检查工作流文件。
- PyPI 上传不在本阶段范围内。待平台矩阵通过，再按独立授权配置 Trusted Publishing 和首发。
- 不设代码行数或上下文 token 降幅指标。没有代表性的现有脚本与调用记录，不能量化节省。
