# Python 3.11 离线依赖包仓库体系 (Windows x64)

本项目面向 Windows x64 / CPython 3.11 离线环境，将 wheel 仓库、依赖可用性检查、许可证证据审计和不可变发布流程整合为一个可验证的工作台。`package311/` 是唯一依赖来源；Dash 和 MCP 共用同一目录分层的核心服务。

---

## 目录结构与模块说明

```
Python311_package/
├── autoinstall.bat            # 基于 pip 的离线全量安装与浏览器解压脚本
├── uv-autoinstall.bat         # 基于 uv 的极速离线安装与浏览器解压脚本
├── run_dashboard.bat          # 一键启动 Dash 可视化管理工作台
├── run_tests.bat              # 一键运行全量离线自动化测试套件
├── offline_catalog.py         # 兼容入口；实现位于 src/offline_package/catalog.py
├── offline_dashboard.py       # 兼容入口；实现位于 src/offline_package/dashboard.py
├── offline_mcp.py             # 兼容入口；实现位于 src/offline_package/mcp_server.py
├── offline_release.py         # 发布工具：构建与核验不可变 release 压缩包与 SHA-256 清单
├── src/offline_package/       # 可安装 Python 包的核心实现
│   ├── catalog.py             # Wheel 审计、依赖分析、离线入库
│   ├── dashboard.py           # Dash UI 适配器
│   ├── mcp_server.py          # MCP stdio 适配器
│   └── assets/                # 随应用包分发的 CSS 资源
├── pwistron.txt               # 生产环境基础全量依赖清单版本锁定表
├── OFFLINE-RELEASE.md         # 离线打包、发布管理与核验规范指南
├── requirements-*.txt         # 指向 config/ 的兼容依赖清单
├── config/                    # UI、MCP、开发工具依赖清单
├── package311/                # 核心轮子库：Windows x64 / Python 3.11 离线 wheel 及资源包
├── docs/                      # 架构、评审、质量门禁与参考资料索引
│   ├── operations/             # UI / MCP 运行与操作指南
│   ├── development/            # 开发环境与贡献指南
│   └── references/             # 历史 PDF 资料，不作为当前运行规范
├── tests/                     # 单元与集成测试套件集合
│   ├── test_offline_catalog.py
│   ├── test_offline_dashboard.py
│   ├── test_offline_mcp.py
│   └── test_uv_autoinstall.py # 独立的较慢安装器集成测试
├── .vscode/                   # MCP、编辑器与任务配置
└── src/offline_package/assets/ # 随 Dash 包分发的静态样式
```

---

## 四大核心模块导航

├── README.md                  # 项目入口与功能总览
├── autoinstall.bat            # 固定发布输入：pip 离线安装
├── uv-autoinstall.bat         # 固定发布输入：uv 离线安装
├── pwistron.txt               # 固定发布输入：部署依赖清单
├── OFFLINE-RELEASE.md         # 固定发布输入：发布说明
├── offline_release.py         # 构建与核验不可变归档
├── offline_catalog.py         # 兼容入口 ─┐
├── offline_dashboard.py       # 兼容入口 ─┼─> src/offline_package/
├── offline_mcp.py             # 兼容入口 ─┘
├── run_*.bat                  # 根目录兼容启动器
├── requirements-*.txt         # 指向 config/ 的兼容清单
├── pyproject.toml             # src 包元数据、console scripts 与 Ruff 配置
├── config/                    # requirements-ui/mcp/dev.txt 实际清单
├── src/offline_package/       # 核心实现与可分发包
│   ├── catalog.py             # wheel 审计、依赖分析、离线入库
│   ├── dashboard.py           # Dash 适配器
│   ├── mcp_server.py          # MCP stdio 适配器
│   └── assets/                # 随 wheel 打包的 CSS
├── tests/                     # 单元、MCP 与安装器集成测试
├── docs/                      # 评审、架构和操作/开发文档
│   ├── operations/            # Dash 与 MCP 使用指南
│   ├── development/           # 开发与贡献指南
│   └── references/            # 历史 PDF 资料
├── .vscode/                   # MCP、编辑器与任务配置
├── package311/                # 本地 Windows x64 / Python 3.11 wheelhouse
├── download/、bk/、release/   # 本地下载、备份和生成归档
└── python_source/             # 保留的历史/上游源码资料
- **特性**：构建带完整 SHA-256 校验和与 release 元数据的只读归档压缩包，保证发布物不可变性。

---

## 快速上手

### 环境准备 (Windows x64 / Python 3.11)
激活当前工作区虚拟环境并安装所需轻量依赖（全量来源于本地离线轮子）：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --no-index --find-links .\package311 --only-binary=:all: -r .\requirements-ui.txt -r .\requirements-mcp.txt
```

### 启动 Dash 管理界面
双击运行 [run_dashboard.bat](run_dashboard.bat) 或在终端中执行：

```powershell
.\.venv\Scripts\python.exe .\offline_dashboard.py --port 8050
```
启动后访问：http://127.0.0.1:8050

### 启动 MCP Server
直接在 VS Code 中通过 Copilot / Agent 启动：VS Code 会自动读取 [.vscode/mcp.json](.vscode/mcp.json) 并接管服务生命周期。

### 运行全量测试套件
双击运行 [run_tests.bat](run_tests.bat) 或在终端中执行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_offline_*.py" -v
```

代码实现位于 `src/offline_package/`；根目录 Python 文件和 `requirements-*.txt` 保留为兼容转发入口，发布必需文件继续遵守根目录路径约定。架构、质量门禁和目录决策见 [架构说明](docs/ARCHITECTURE.md)、[质量门禁](docs/QUALITY-GATES.md) 和 [目录评审](docs/STRUCTURE-REVIEW.md)。开发规则见 [贡献指南](docs/development/CONTRIBUTING.md)。

源码 ZIP 范围及在其他电脑上传 GitHub 的步骤见 [GITHUB-UPLOAD.md](GITHUB-UPLOAD.md)。

---

## 安全与合规说明

1. **许可证声明与法律合规**：元数据提取的许可证和证据仅供法务与架构师参考审查，不代表自动法律批准。对于 GPL/LGPL、Dual License 或未声明许可的包，应重点核查分发义务与源代码开放要求。
2. **隔离安装测试非操作系统沙箱**：Python 虚拟环境 (`venv`) 提供包依赖隔离，但在安装过程中（如 wheel 含有 `.pth` 脚本或启动钩子）仍使用当前用户权限运行。请确保待入库轮子来源可信。
3. **不可变原则**：已入库版本严禁覆盖替换，任何变更必须以递增版本号发布，确保生产环境构建的可追溯性与确定性。
