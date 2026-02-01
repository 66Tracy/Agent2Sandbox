# Agent2Sandbox 架构设计

## 项目概述

Agent2Sandbox 是一个轻量级的通用 Agent 和 OpenSandbox 交互框架。其核心理念是**环境即工具（Environment as Tools）**——Agent 不需要理解环境的底层实现，只需要通过统一的工具调用协议与之交互。框架遵循一个连续的循环逻辑：Agent（即 LLM）给出指令/工具执行，环境返回反馈结果，直到任务完成。

## 核心设计理念

### 1. 环境即工具（Environment as Tools）

将沙箱环境抽象为一组工具接口，Agent 通过标准的工具调用协议与沙箱交互，无需了解底层实现细节。

- **工具接口标准化**：所有沙箱操作（命令执行、文件操作、代码解释）都通过统一的工具接口暴露
- **执行结果标准化**：沙箱的输出、错误、状态都以统一的格式返回给 Agent
- **状态封装**：沙箱的状态对 Agent 透明，Agent 只关心工具调用和结果

### 2. 交互循环

```
┌─────────┐
│  Agent  │ (LLM)
└────┬────┘
     │
     │ 1. 给出指令 / 选择工具
     ▼
┌──────────────┐
│  Agent2Sandbox│ (中间层)
│   Framework  │
└──────┬───────┘
       │
       │ 2. 转换为沙箱操作
       ▼
┌──────────────┐
│  OpenSandbox │ (沙箱运行时)
└──────┬───────┘
       │
       │ 3. 执行操作
       ▼
┌──────────────┐
│  Sandboxed   │ (隔离环境)
│   Container  │
└──────┬───────┘
       │
       │ 4. 返回执行结果
       ▼
┌──────────────┐
│  Agent2Sandbox│
└──────┬───────┘
       │
       │ 5. 格式化为工具结果
       ▼
┌──────────────┐
│  Agent       │
└──────────────┘
    (根据结果决定下一步)
```

## 架构分层

```
┌─────────────────────────────────────────────────────────────┐
│                      Agent Layer                             │
│                  (OpenAI / Anthropic / ...)                 │
└──────────────────────────┬──────────────────────────────────┘
                           │ OpenAI Tools Protocol
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  Agent2Sandbox Layer                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Tool Adapter│  │  Result      │  │  State       │      │
│  │              │  │  Converter   │  │  Manager     │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│  ┌────────────────────────────────────────────────────┐     │
│  │         Agent Orchestrator (协调器)                │     │
│  │  - 任务分解  - 工具调度  - 状态管理  - 循环控制     │     │
│  └────────────────────────────────────────────────────┘     │
└──────────────────────────┬──────────────────────────────────┘
                           │ Sandbox Protocol
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  OpenSandbox SDK Layer                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │   Sandbox   │  │ Filesystem  │  │  Commands   │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
│  ┌──────────────────────────────────────────────┐         │
│  │          CodeInterpreter (可选)              │         │
│  └──────────────────────────────────────────────┘         │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP/WebSocket
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  OpenSandbox Runtime                        │
│                  (Docker / Kubernetes)                      │
└─────────────────────────────────────────────────────────────┘
```

## 核心组件

### 1. Tool Adapter（工具适配器）

负责将 OpenAI 风格的工具调用转换为 OpenSandbox 操作。

**职责**：
- 将 Agent 的工具调用请求转换为沙箱操作
- 将沙箱操作结果转换为 OpenAI 工具调用响应格式
- 管理工具定义（schema）

**工具定义**：
```python
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_command",
            "description": "Execute a shell command in the sandbox",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute"
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the sandbox",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The file path to read"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file in the sandbox",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The file path to write"
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write"
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_code",
            "description": "Execute code in the code interpreter",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The code to execute"
                    },
                    "language": {
                        "type": "string",
                        "enum": ["python", "java", "javascript", "go", "bash"],
                        "description": "The programming language"
                    }
                },
                "required": ["code", "language"]
            }
        }
    }
]
```

### 2. Result Converter（结果转换器）

负责将沙箱执行结果转换为 Agent 可理解的格式。

**职责**：
- 解析沙箱返回的 stdout、stderr、exit_code
- 格式化文件内容
- 提取代码执行结果
- 处理错误信息

### 3. State Manager（状态管理器）

管理 Agent 与沙箱交互的会话状态。

**职责**：
- 维护沙箱生命周期
- 跟踪任务进度
- 存储中间结果
- 管理工具调用历史

### 4. Agent Orchestrator（Agent 协调器）

协调 Agent、沙箱和工具之间的交互。

**职责**：
- 发送工具定义给 Agent
- 接收 Agent 的工具调用请求
- 调用 Tool Adapter 执行操作
- 将结果返回给 Agent
- 判断任务是否完成

## 数据流

### 1. 初始化流程

```
用户发起任务
    │
    ▼
Agent Orchestrator 初始化
    │
    ▼
启动 OpenSandbox 实例
    │
    ▼
注册工具定义到 Agent
    │
    ▼
等待 Agent 首次指令
```

### 2. 工具调用流程

```
Agent 发起工具调用
    │
    ├─ tool_name
    ├─ arguments
    ▼
Tool Adapter 验证并转换
    │
    ├─ execute_command → sandbox.commands.run()
    ├─ read_file → sandbox.files.read_file()
    ├─ write_file → sandbox.files.write_file()
    ├─ run_code → interpreter.codes.run()
    ▼
OpenSandbox 执行操作
    │
    ▼
Result Converter 转换结果
    │
    ├─ 提取输出
    ├─ 格式化错误
    ▼
返回给 Agent
    │
    ▼
Agent 决定下一步
    ├─ 继续调用工具
    ├─ 任务完成
    └─ 放弃任务
```

## 技术栈

| 组件 | 技术选择 |
|------|----------|
| Python 版本 | 3.10+ |
| 包管理 | uv |
| OpenSandbox SDK | opensandbox, opensandbox-code-interpreter |
| LLM 集成 | OpenAI API (支持兼容格式) |
| 异步框架 | asyncio |
| 配置管理 | Pydantic |

## 项目结构

```
Agent2Sandbox/
├── agent2sandbox/              # 主包目录
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── orchestrator.py     # Agent 协调器
│   │   ├── state_manager.py    # 状态管理器
│   │   └── types.py            # 类型定义
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── tool_adapter.py     # 工具适配器
│   │   └── result_converter.py # 结果转换器
│   ├── tools/
│   │   ├── __init__.py
│   │   └── definitions.py      # 工具定义
│   └── llm/
│       ├── __init__.py
│       └── client.py           # LLM 客户端
├── test/                       # 测试目录
│   └── test1-sandbox-interaction.py
├── pyproject.toml              # 项目配置
├── architecture.md            # 架构文档
└── plan.md                    # 实现计划
```

## 扩展性设计

### 1. 多 LLM 支持

通过抽象 LLM 客户端接口，支持多种 LLM 提供商（OpenAI、Anthropic、本地模型等）。

### 2. 自定义工具

允许注册自定义工具，扩展框架能力。

### 3. 多沙箱支持

框架设计支持同时管理多个沙箱实例，适用于并行任务场景。

### 4. 任务模式扩展

支持多种任务模式：
- 单轮任务
- 多轮对话
- 自主迭代任务
- 多步骤工作流

## 安全性考虑

1. **沙箱隔离**：所有代码和命令在隔离的容器中执行
2. **权限控制**：沙箱资源限制（CPU、内存、网络）
3. **输入验证**：工具调用参数验证
4. **超时控制**：操作超时自动终止
