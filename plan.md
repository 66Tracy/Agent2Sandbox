# Agent2Sandbox 项目计划与进展

## 项目目标

构建一个轻量级的通用 Agent 和 OpenSandbox 交互框架，核心是"环境即工具（Environment as Tools）"理念。通过完善测试用例 `test1-sandbox-interaction.py` 来验证框架的基础功能。

## 已完成任务总结

### 阶段一：项目初始化 ✅

**完成内容：**
- ✅ 1.1 编写 `architecture.md` - 描述项目整体设计
- ✅ 1.2 初始化项目结构
- ✅ 1.3 创建 `pyproject.toml` 配置文件
- ⏳ 1.4 使用 uv 创建虚拟环境（已完成环境同步）

**文件清单：**
```
Agent2Sandbox/
├── pyproject.toml
├── architecture.md
├── plan.md
├── agent2sandbox/
│   ├── __init__.py
│   ├── core/
│   ├── adapters/
│   ├── tools/
│   └── llm/
└── test/
```

### 阶段二：核心类型定义 ✅

**完成内容：**
- ✅ 2.1 创建 `core/types.py` - 定义核心数据类型
  - `ToolCall` - 工具调用请求
  - `ToolResult` - 工具执行结果
  - `SandboxConfig` - 沙箱配置
  - `AgentState` - Agent 状态
  - `ToolName` - 工具名称枚举
  - `ToolStatus` - 工具状态枚举
  - `LLMMessage` - LLM 消息
  - `LLMResponse` - LLM 响应
- ✅ 2.2 创建 `core/__init__.py`

### 阶段三：工具适配器 ✅

**完成内容：**
- ✅ 3.1 创建 `adapters/tool_adapter.py`
  - `ToolAdapter` 类 - 适配工具调用到沙箱操作
  - `execute()` 方法 - 执行工具调用
  - 支持的工具：
    - `execute_command` - 执行 shell 命令
    - `read_file` - 读取文件
    - `write_file` - 写入文件
    - `list_files` - 列出文件
    - `run_code` - 执行代码
- ✅ 3.2 创建 `adapters/result_converter.py`
  - `ResultConverter` 类 - 转换结果格式
  - `to_message()` - 转换为消息
  - `to_tool_response()` - 转换为 OpenAI 工具响应格式
- ✅ 3.3 创建 `adapters/__init__.py`

### 阶段四：工具定义 ✅

**完成内容：**
- ✅ 4.1 创建 `tools/definitions.py`
  - 定义 5 个工具（execute_command, read_file, write_file, list_files, run_code）
  - 生成 OpenAI 格式的工具 schema
  - 提供查询工具 schema 的函数
- ✅ 4.2 创建 `tools/__init__.py`

**工具列表：**
| 工具名 | 描述 | 参数 |
|--------|------|------|
| execute_command | 执行 shell 命令 | command |
| read_file | 读取文件内容 | path |
| write_file | 写入文件内容 | path, content |
| list_files | 列出目录文件 | path, pattern |
| run_code | 执行代码 | code, language |

### 阶段五：状态管理器 ✅

**完成内容：**
- ✅ 5.1 创建 `core/state_manager.py`
  - `StateManager` 类 - 管理 Agent 和沙箱状态
  - `sandbox` 属性 - 沙箱实例
  - `code_interpreter` 属性 - 代码解释器实例
  - `record_tool_call()` - 记录工具调用历史
  - `record_result()` - 记录结果历史
  - `get_history()` - 获取历史记录
  - `get_last_result()` - 获取最近结果
  - `is_initialized()` - 检查初始化状态
  - `get_step_count()` - 获取步数计数

### 阶段六：Agent 协调器 ✅

**完成内容：**
- ✅ 6.1 创建 `core/orchestrator.py`
  - `AgentOrchestrator` 类 - 协调 Agent、工具和沙箱交互
  - `initialize()` - 初始化 Agent 和沙箱
  - `execute_tool()` - 执行单个工具调用
  - `execute_tools()` - 执行多个工具调用（并行）
  - `step()` - 执行单步交互
  - `run()` - 运行完整的任务循环
  - `get_tools()` - 获取工具定义
  - `close()` - 关闭和清理资源

### 阶段七：LLM 客户端 ✅

**完成内容：**
- ✅ 7.1 创建 `llm/client.py`
  - `LLMClient` - 抽象基类
  - `OpenAIClient` - OpenAI API 客户端实现
    - 支持 OpenAI 兼容格式
    - 支持工具调用
  - `MockLLMClient` - Mock 客户端用于测试
    - 支持预定义响应
    - 自动回退逻辑
- ✅ 7.2 创建 `llm/__init__.py`

### 阶段八：主包导出 ✅

**完成内容：**
- ✅ 8.1 创建 `agent2sandbox/__init__.py`
  - 导出所有主要类和函数
  - 清晰的模块文档字符串

**导出清单：**
```python
__all__ = [
    "AgentOrchestrator",
    "StateManager",
    "get_tool_definitions",
    "LLMClient",
    "OpenAIClient",
    "MockLLMClient",
    "ToolCall",
    "ToolResult",
    "SandboxConfig",
    "AgentState",
    "ToolName",
    "ToolStatus",
    "LLMMessage",
    "LLMResponse",
]
```

### 阶段九：测试用例 ✅

**完成内容：**
- ✅ 9.1 创建 `test/test_framework_basic.py` - 基本框架测试（无需真实沙箱）
- ✅ 9.2 完善 `test/test1-sandbox-interaction.py` - 完整沙箱交互测试

**测试结果：**

#### 基本框架测试 (`test_framework_basic.py`) - **5/5 通过** ✅

| 测试 | 结果 | 描述 |
|------|------|------|
| 工具定义 | ✅ | 5 个工具都正确定义和导出 |
| Mock LLM 客户端 | ✅ | 可以正常返回预定义响应和回退 |
| 工具调用和结果 | ✅ | 数据结构正确，支持所有工具类型 |
| 沙箱配置 | ✅ | 默认配置和自定义配置创建正常 |
| 枚举类型 | ✅ | ToolName 和 ToolStatus 枚举值正确 |

#### 完整沙箱测试 (`test1-sandbox-interaction.py`) - ⏳ 需环境

| 测试 | 状态 | 需求 |
|------|------|------|
| 基本沙箱交互 | ⏳ | 需要运行中的 OpenSandbox Server |
| Agent2Sandbox 工具执行 | ⏳ | 需要运行中的 OpenSandbox Server |
| 多轮交互 | ⏳ | 需要运行中的 OpenSandbox Server |
| 自定义工具处理器 | ⏳ | 需要运行中的 OpenSandbox Server |

### 阶段十：文档和示例 ⏳

**待完成内容：**
- ⏳ 10.1 创建 `README.md` - 项目使用文档
- ⏳ 10.2 添加基本使用示例

## 当前项目结构

```
Agent2Sandbox/
├── pyproject.toml              # 项目配置（uv 包管理）
├── architecture.md            # 架构设计文档 ✅
├── plan.md                   # 本文件：计划与进展 ✅
├── agent2sandbox/              # 主包目录
│   ├── __init__.py          # 包导出 ✅
│   ├── core/                 # 核心组件 ✅
│   │   ├── __init__.py
│   │   ├── types.py         # 数据类型定义 ✅
│   │   ├── state_manager.py # 状态管理 ✅
│   │   └── orchestrator.py # Agent 协调器 ✅
│   ├── adapters/             # 适配器 ✅
│   │   ├── __init__.py
│   │   ├── tool_adapter.py  # 工具适配器 ✅
│   │   └── result_converter.py # 结果转换器 ✅
│   ├── tools/                # 工具定义 ✅
│   │   ├── __init__.py
│   │   └── definitions.py  # 工具 Schema ✅
│   └── llm/                 # LLM 客户端 ✅
│       ├── __init__.py
│       └── client.py        # LLM 客户端实现 ✅
└── test/                   # 测试目录
    ├── test1-sandbox-interaction.py  # 完整沙箱测试 ⏳
    └── test_framework_basic.py        # 基本框架测试 ✅
```

## 技术栈

| 组件 | 技术选择 | 状态 |
|------|----------|------|
| Python 版本 | 3.10+ | ✅ |
| 包管理 | uv | ✅ |
| OpenSandbox SDK | opensandbox, opensandbox-code-interpreter | ✅ |
| LLM 集成 | OpenAI API (兼容格式) | ✅ |
| 异步框架 | asyncio | ✅ |
| 类型验证 | pydantic | ✅ |

## 核心功能清单

| 功能 | 状态 | 说明 |
|------|------|------|
| 沙箱生命周期管理 | ✅ | 创建、启动、关闭沙箱 |
| 工具定义 | ✅ | 5 个工具，OpenAI 格式 |
| 工具适配 | ✅ | 将工具调用转换为沙箱操作 |
| 结果转换 | ✅ | 格式化沙箱结果 |
| 状态管理 | ✅ | 记录工具调用和结果历史 |
| Agent 协调 | ✅ | 单步和完整任务循环 |
| LLM 客户端 | ✅ | OpenAI 实现和 Mock 实现 |
| 命令执行 | ✅ | shell 命令工具 |
| 文件操作 | ✅ | 读取、写入、列出文件 |
| 代码执行 | ✅ | 多语言代码解释器 |

## 下一步计划

### 短期任务

1. **完成基本测试** (可选)
   - 运行完整沙箱测试需要：
     - 安装 Docker
     - 启动 OpenSandbox Server
     - 执行 `test1-sandbox-interaction.py`

2. **完善文档**
   - 创建 `README.md`
   - 添加使用示例
   - 添加 API 文档

### 中期扩展

1. **错误处理增强**
   - 更详细的错误信息
   - 重试机制
   - 超时处理

2. **状态管理增强**
   - 持久化状态（支持恢复）
   - 多沙箱管理
   - 资源使用监控

3. **工具扩展**
   - 添加更多工具（如：下载文件、搜索内容等）
   - 支持自定义工具注册
   - 工具权限控制

### 长期目标

1. **多 Agent 支持**
   - 支持同时运行多个 Agent
   - Agent 间通信机制
   - 任务队列和调度

2. **高级特性**
   - 流式输出支持
   - 代码调试功能
   - 沙箱快照和恢复
   - 性能分析和优化

3. **集成扩展**
   - 其他 LLM 提供商支持（Anthropic、本地模型等）
   - 更多运行时支持（Kubernetes 等）
   - 监控和日志集成

## 待修复问题

### 已知问题

1. **uv 配置警告**
   - `tool.uv.dev-dependencies` 已弃用
   - 建议：使用 `dependency-groups.dev` 替代
   - 影响：不影响功能，仅警告

2. **完整测试依赖环境**
   - 需要运行中的 Docker
   - 需要运行中的 OpenSandbox Server
   - 当前无法在 CI/CD 中自动测试

## 运行完整测试的步骤

如需测试完整的沙箱交互功能，请按以下步骤操作：

```bash
# 1. 启动 OpenSandbox Server（需要 Docker）
cd /c/work_dir/work/OpenSandbox/server
uv sync
uv run python -m src.main

# 2. 在另一个终端运行完整测试
cd /c/work_dir/work/Agent2Sandbox
uv run python test/test1-sandbox-interaction.py
```

## 测试执行记录

**最后一次执行时间：** 2026-02-01

**基本框架测试结果：**
```
Passed: 5/5

All tests passed!
```

**完整沙箱测试状态：**
- ⏳ 等待 Docker 和 OpenSandbox Server 环境就绪

## 版本信息

- **当前版本：** 0.1.0
- **Python 要求：** >=3.10
- **主要依赖：**
  - opensandbox>=0.1.0
  - opensandbox-code-interpreter>=0.1.0
  - pydantic>=2.0.0
  - openai>=1.0.0

## 贡献指南

如需继续开发或贡献，请参考：

1. **添加新工具**
   - 在 `tools/definitions.py` 中添加工具定义
   - 在 `adapters/tool_adapter.py` 中实现执行逻辑
   - 更新测试用例

2. **支持新 LLM**
   - 在 `llm/client.py` 中实现新的客户端类
   - 确保符合 `LLMClient` 接口
   - 添加使用示例

3. **修复问题**
   - 查看上述"待修复问题"列表
   - 添加对应的测试用例
   - 更新本文档

## 总结

Agent2Sandbox 项目初步架构已完整实现，核心功能均已到位：

- ✅ 完整的类型系统
- ✅ 工具适配和转换机制
- ✅ 状态管理
- ✅ Agent 协调器
- ✅ LLM 客户端（OpenAI + Mock）
- ✅ 5 个基础工具
- ✅ 基本框架测试通过

项目已具备"环境即工具"的核心能力，可以进行下一步的功能扩展和集成测试。
