# Agent2Sandbox 架构设计

## 项目概述

Agent2Sandbox 是一个轻量级的通用 Agent 和 OpenSandbox 交互框架。其核心设计理念是**基于对话状态的交互循环**（Conversation-Based Interaction Loop）——Agent 通过维护完整的对话历史与 LLM 和沙箱环境进行多轮交互，直到任务完成。

## 核心设计理念

### 1. 对话状态管理（Conversation State Management）

Agent 维护完整的对话历史，包括：
- **用户消息**：用户的初始请求和后续反馈
- **Assistant 消息**：LLM 的响应，包括文本内容和工具调用
- **工具结果消息**：工具执行的输出和错误信息

这种设计使 Agent 能够：
- 理解上下文：LLM 可以看到之前的所有交互
- 避免重复：知道哪些操作已经执行过
- 正确响应：根据工具结果给出下一步操作

### 2. 环境抽象化（Environment Abstraction）

将沙箱环境抽象为一组标准化工具接口，Agent 通过统一的工具调用协议与沙箱交互。

**关键优势：**
- **工具接口标准化**：所有沙箱操作（命令执行、文件操作、代码执行）都通过统一的工具接口暴露
- **执行结果标准化**：沙箱的输出、错误、状态都以统一的格式返回给 Agent
- **状态封装**：沙箱的生命周期对 Agent 透明，Agent 只关心工具调用和结果
- **配置灵活性**：支持连接到远程 OpenSandbox Server 或本地 Docker 环境

### 3. 交互循环设计

```
┌─────────┐
│  Agent  │ (LLM)
└────┬────┘
     │
     │1. 解析用户请求 + 历史上下文
     ▼
┌──────────────┐
│  Agent2Sandbox│ (中间层)
│   Framework  │
└──────┬───────┘
     │
     │2. 生成 LLM 请求（包含工具定义）
     ▼
┌──────────────┐
│   LLM API    │ (DeepSeek / OpenAI / ...)
└──────────────┘
     │
     │3. 返回工具调用或最终响应
     ▼
┌──────────────┐
│  Agent2Sandbox│ (中间层)
│   Framework  │
└──────┬───────┘
     │
     │4a. 如果有工具调用 → 转换为沙箱操作
     │4b. 如果是最终响应 → 提取并添加到历史
     ▼
┌──────────────┐
│  OpenSandbox │ (沙箱运行时)
└──────┬───────┘
     │
     │5. 执行命令/代码/文件操作
     ▼
┌──────────────┐
│  Sandboxed   │ (隔离容器)
│   Container  │
└──────┬───────┘
     │
     │6. 返回执行结果
     ▼
┌──────────────┐
│  Agent2Sandbox│ (中间层)
└──────────┬───────┘
     │
     │7. 格式化为工具结果
     │8. 更新对话历史
     ▼
┌──────────────┐
│  Agent       │
└────────────────┘
     (根据结果决定下一步或完成任务)
```

## 架构分层

```
┌─────────────────────────────────────────────────────────────┐
│                      Agent Layer                             │
│                  (OpenAI / Anthropic / DeepSeek)            │
└──────────────────────────┬──────────────────────────────────┘
                            │ LLM Tools Protocol
                            │
                            │ (OpenAI Function Calling)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  Agent2Sandbox Layer                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Orchestrator │  │ Conversation │  │  Tool        │      │
│  │  (协调器)    │  │ History     │  │  Adapter      │      │
│  │              │  │  Manager     │  │              │      │
│  │  - 任务分解   │  │  - 维护完整 │  │  - 转换工具调用│      │
│  │  - 工具调度   │  │    对话历史 │  │    为沙箱操作 │      │
│  │  - 循环控制   │  │              │  │  - 转换执行结果│      │
│  │  - 状态管理   │  │              │  │  - 错误处理    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│  ┌────────────────────────────────────────────────────┐     │
│  │         State Manager (状态管理器)              │     │
│  │  - 沙箱生命周期                              │     │
│  │  - 对话历史（Conversation History）           │     │
│  │  - 任务进度                                    │     │
│  └────────────────────────────────────────────────────┘     │
└──────────────────────────┬──────────────────────────────────┘
                            │ Sandbox Protocol
                            │ (HTTP/WebSocket + ConnectionConfig)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  OpenSandbox SDK Layer                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │  Sandbox   │  │ Filesystem  │  │  Commands   │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
│  ┌──────────────────────────────────────────────┐         │
│  │          CodeInterpreter (可选)              │         │
│  │  - Python 代码执行                          │         │
│  │  - 多语言支持（Python/Java/JS/Go/TS）     │         │
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

### 1. Orchestrator（协调器）

核心协调器，负责整个 Agent 交互流程的编排。

**关键职责：**

1. **对话历史管理（Conversation History Management）**
   - 维护 `conversation_history` 列表，存储所有消息
   - 包括用户消息、Assistant 消息、工具结果消息
   - 每次请求时传递完整历史给 LLM

2. **LLM 交互**
   - 发送包含完整对话历史的请求给 LLM
   - 支持工具定义注入
   - 解析 LLM 返回的工具调用和响应

3. **工具执行调度**
   - 接收 LLM 返回的工具调用
   - 通过 ToolAdapter 转换为沙箱操作
   - 并行或顺序执行工具
   - 收集执行结果

4. **对话历史更新**
   - 将 Assistant 消息（包含工具调用）添加到历史
   - 将工具结果消息添加到历史
   - 确保 LLM 能看到完整的执行上下文

5. **任务完成判断**
   - 检查 `finish_reason`（stop/tool_calls）
   - 检查是否还有工具调用
   - 支持自定义完成检查函数
   - 控制最大步数

**关键方法：**
```python
class AgentOrchestrator:
    def __init__(self, config, llm_client):
        self.config = config
        self.llm_client = llm_client
        self.conversation_history: List[LLMMessage] = []
        self.state_manager = StateManager(config)
        self.tool_adapter: Optional[ToolAdapter] = None
        self.result_converter = ResultConverter()

    async def initialize(self):
        # 创建沙箱并初始化工具适配器
        sandbox = await Sandbox.create(...)
        self.state_manager.sandbox = sandbox
        code_interpreter = await CodeInterpreter.create(sandbox)
        self.state_manager.code_interpreter = code_interpreter
        self.tool_adapter = ToolAdapter(sandbox, code_interpreter)
        self.conversation_history = []

    async def run(self, user_message, max_steps=10, completion_check=None, on_step=None):
        # 添加初始用户消息到历史
        self.conversation_history.append(LLMMessage(role="user", content=user_message))

        for step in range(max_steps):
            # 使用完整对话历史调用 LLM
            response = await self.llm_client.chat(
                messages=self.conversation_history,
                tools=get_tool_definitions(),
            )

            # 如果有工具调用，执行并添加到历史
            if response.tool_calls:
                results = await self.execute_tools(response.tool_calls)

                # 添加 Assistant 消息（含工具调用）
                self.conversation_history.append(
                    LLMMessage(
                        role="assistant",
                        content=response.content or "",
                        tool_calls=response.tool_calls,
                    )
                )

                # 添加工具结果消息
                for tool_call, result in zip(response.tool_calls, results):
                    self.conversation_history.append(
                        LLMMessage(
                            role="tool",
                            content=result.output or result.error or "No output",
                            tool_call_id=tool_call.call_id,
                            name=tool_call.name.value,
                        )
                    )
            else:
                # 最终响应，添加到历史
                if response.content:
                    self.conversation_history.append(
                        LLMMessage(role="assistant", content=response.content)
                    )

            # 调用步骤回调
            if on_step:
                on_step(step + 1, response)

            # 检查任务是否完成
            if completion_check and completion_check(response):
                break

            if not response.tool_calls:
                break

        return response
```

### 2. Tool Adapter（工具适配器）

将 OpenAI 格式的工具调用转换为 OpenSandbox 操作。

**关键职责：**
- 将 Agent 的工具调用请求转换为沙箱操作
- 将沙箱操作结果转换为 Agent 可理解的格式
- 处理 OpenSandbox 的返回结构和错误

**支持的工具：**

1. **execute_command** - 执行 shell 命令
   - 参数：`command` (string)
   - 实现：`sandbox.commands.run(command)`
   - 返回：stdout, stderr, exit_code
   - 错误处理：检查 `result.error` 而非 `exit_code`

2. **read_file** - 读取文件
   - 参数：`path` (string)
   - 实现：`sandbox.files.read_file(path)`
   - 返回：文件内容（string）
   - 错误处理：文件不存在、权限错误

3. **write_file** - 写入文件
   - 参数：`path` (string), `content` (string)
   - 实现：`sandbox.files.write_file(path, content)`
   - 返回：成功消息

4. **run_code** - 执行代码
   - 参数：`code` (string), `language` (string: python/java/js/go/bash/ts)
   - 实现：`code_interpreter.codes.run(code, language=SupportedLanguage)`
   - 返回：stdout, stderr, result（最后表达式的值）
   - 错误处理：代码语法错误、运行时错误

5. **list_files** - 列出文件
   - 参数：`path` (string), `pattern` (string, 默认: "*")
   - 实现：`sandbox.files.search(SearchEntry(path, pattern))`
   - 返回：文件路径列表
   - 错误处理：目录不存在、权限错误

### 3. State Manager（状态管理器）

管理 Agent 与沙箱交互的状态和对话历史。

**职责：**
- 维护沙箱生命周期（创建、使用、销毁）
- 跟踪任务进度（步骤计数）
- 存储中间结果（如果需要）
- 维护沙箱 ID 和其他元数据

**状态追踪：**
```python
@dataclass
class AgentState:
    sandbox_id: Optional[str]
    is_initialized: bool
    tool_call_history: List[ToolCall]
    result_history: List[ToolResult]
    current_step: int
```

### 4. Conversation History Manager（对话历史管理器）

**新设计的关键组件：**

维护完整的对话历史，支持多轮交互：

```python
# 对话历史结构
conversation_history = [
    # 消息1: 用户初始请求
    LLMMessage(role="user", content="分析数据..."),

    # 消息2: LLM 响应（含工具调用）
    LLMMessage(
        role="assistant",
        content="我将执行分析...",
        tool_calls=[ToolCall(...)]
    ),

    # 消息3: 工具执行结果
    LLMMessage(
        role="tool",
        content="分析结果...",
        tool_call_id="call_xxx",
        name="run_code"
    ),

    # 消息4: LLM 最终响应
    LLMMessage(role="assistant", content="分析完成"),
]
```

**优势：**
- **上下文连续性**：LLM 始终能看到完整的交互历史
- **避免重复**：知道哪些操作已经执行
- **调试友好**：完整的对话历史便于调试
- **智能决策**：基于完整历史做出更好的决策

### 5. Tool Definitions（工具定义）

提供标准化的工具定义给 LLM，支持 Function Calling。

**工具定义格式（OpenAI 标准）：**
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
    # ... 其他工具定义
]
```

### 6. Result Converter（结果转换器）

将沙箱执行结果转换为 Agent 可理解的格式。

**职责：**
- 提取 stdout/stderr
- 格式化文件内容
- 提取代码执行结果
- 处理错误信息

### 7. LLM Client Abstraction（LLM 客户端抽象）

支持多种 LLM 提供商的统一接口。

**接口设计：**
```python
class LLMClient(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[dict]] = None,
    ) -> LLMResponse:
        """Send a chat request to LLM."""
        pass
```

**实现：**
- `OpenAIClient` - 支持 OpenAI 兼容 API（包括 DeepSeek）
- `MockLLMClient` - 用于测试的模拟客户端

## 交互流程详解

### 完整任务执行流程

```
1. [初始化]
   ├─ 用户输入任务
   ├─ Orchestrator.initialize()
   │  └─ 创建 Sandbox 实例
   │     ├─ 使用 ConnectionConfig 连接到远程/本地服务器
   │     ├─ 配置 domain 和 api_key
   │     └─ 初始化工具适配器
   │        └─ 创建 CodeInterpreter（如果使用 code-interpreter 镜像）

2. [任务循环 - 最多 max_steps 步]
   ├─ 循环（step = 1 到 max_steps）
   │
   │  3. [LLM 请求]
   │  ├─ 构建请求：
   │  │  └─ messages = conversation_history (包含所有历史消息)
   │  ├─ tools = get_tool_definitions()
   │  └─ 发送请求给 LLM API
   │
   │  4. [处理 LLM 响应]
   │  ├─ 检查 response.tool_calls
   │  │
   │  ├─ 如果有工具调用：
   │  │  ├─ 并行执行所有工具
   │  │  │  └─ results = await execute_tools(tool_calls)
   │  │  │
   │  │  ├─ 添加 Assistant 消息到历史
   │  │  │  └─ conversation_history.append(
   │  │  │     LLMMessage(role="assistant", content=..., tool_calls=tool_calls)
   │  │  │ )
   │  │  │
   │  │  ├─ 添加工具结果消息到历史
   │  │  │  ├─ for tool_call, result in zip(tool_calls, results):
   │  │  │  │  └─ conversation_history.append(
   │  │  │  │       LLMMessage(role="tool", content=..., tool_call_id=..., name=...)
   │  │  │  │   )
   │  │  │
   │  │  └─ 返回工具结果给 Agent
   │  │
   │  └─ 如果没有工具调用：
   │  │     ├─ 添加 Assistant 消息到历史
   │  │     ├─ conversation_history.append(
   │  │     │     LLMMessage(role="assistant", content=response.content)
   │  │     │   )
   │  │     └─ break 循环
   │
   │  5. [步骤回调]
   │  └─ on_step(step, response)
   │
   └─ 6. [任务完成]
      └─ 返回最终 LLMResponse

3. [清理]
   └─ Orchestrator.close()
      └─ 关闭 Sandbox 并释放资源
```

### 多轮对话示例

**场景：数据分析任务**

```
Step 1:
  User: "分析数据 [10, 20, 30...]"
    ↓
  LLM Response: "我将执行分析..."
    Tool Calls: [run_code(code="import numpy...")]
    ↓
  Execution Result: "[output of calculation]"
    ↓
  History Update:
    - Add: Assistant message with tool calls
    - Add: Tool result message

Step 2:
  LLM Request (with full history):
    Messages:
      1. User: "分析数据..."
      2. Assistant: "我将执行..." + [tool calls]
      3. Tool: "[output]" (tool_call_id="xxx")
    ↓
  LLM Response: "结果已计算..."
    Tool Calls: [write_file(path="/tmp/analysis.txt", content="...")]
    ↓
  Execution Result: "File written successfully"
    ↓
  History Update:
    - Add: Assistant message with tool calls
    - Add: Tool result message

Step 3:
  LLM Request (with full history):
    Messages:
      1. User: "分析数据..."
      2. Assistant: "我将执行..." + [tool calls]
      3. Tool: "[output]" (tool_call_id="xxx")
      4. Assistant: "结果已计算..." + [tool calls]
      5. Tool: "File written" (tool_call_id="yyy")
    ↓
  LLM Response: "分析完成！平均值是 55..."
    Tool Calls: None
    ↓
  History Update:
    - Add: Assistant message (no tool calls)

Step 4:
  Check: No tool calls → Break loop
  Final Response: "分析完成！平均值是 55..."
```

## 配置管理

### 环境变量支持

框架支持通过环境变量和配置文件进行配置：

**关键配置项：**
- `SANDBOX_DOMAIN` - OpenSandbox 服务器地址（默认: "localhost:8080"）
- `SANDBOX_API_KEY` - OpenSandbox API 密钥（可选）
- `SANDBOX_IMAGE` - 沙箱镜像
- `BASE_URL` - LLM API 基础 URL
- `API_KEY` - LLM API 密钥
- `MODEL_NAME` - 使用的模型名称
- `MAX_STEPS` - 最大执行步数

### .env 文件

```env
# LLM 配置
BASE_URL=https://api.deepseek.com
API_KEY=your_api_key_here
MODEL_NAME=deepseek-chat

# Sandbox 配置
SANDBOX_DOMAIN=localhost:8080
SANDBOX_API_KEY=optional_api_key
SANDBOX_IMAGE=sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.1
MAX_STEPS=10
```

### SandboxConfig 配置

```python
@dataclass
class SandboxConfig:
    """沙箱配置"""
    image: str = "sandbox-registry.../code-interpreter:v1.0.1"
    entrypoint: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    timeout: timedelta = timedelta(minutes=10)
    cpu_limit: Optional[float] = None
    memory_limit: Optional[int] = None
    domain: Optional[str] = None        # 新增：远程服务器地址
    api_key: Optional[str] = None       # 新增：API 密钥
```

## 连接配置

### ConnectionConfig

使用 OpenSandbox 的 `ConnectionConfig` 建立与沙箱的连接：

```python
from opensandbox.config import ConnectionConfig
from datetime import timedelta

connection_config = ConnectionConfig(
    domain=os.getenv("SANDBOX_DOMAIN", "localhost:8080"),
    api_key=os.getenv("SANDBOX_API_KEY"),
    request_timeout=timedelta(seconds=60),
)

sandbox = await Sandbox.create(
    image,
    connection_config=connection_config,
    entrypoint=["/opt/opensandbox/code-interpreter.sh"],
)
```

**支持的连接方式：**
- **远程服务器**：通过 HTTP/WebSocket 连接到 OpenSandbox Server
- **本地 Docker**：直接使用 Docker API（不需要单独的服务器）

## 数据流

### LLM 交互数据流

```
┌─────────────────────────────────────────────────────┐
│  Orchestrator                      │
└──────────────────┬──────────────────────────────┘
                   │
                   │ 1. 构建请求
                   ▼
         ┌──────────────────────────────┐
         │  conversation_history      │
         │  - User Messages         │
         │  - Assistant Messages     │
         │  - Tool Result Messages │
         └──────────────────────────┘
                   │
                   │ 2. 发送给 LLM
                   ▼
         ┌──────────────────────────────┐
         │  LLM Client              │
         └────────────────┬─────────────┘
                        │
                        │ 3. 接收响应
                        ▼
         ┌──────────────────────────────┐
         │  LLMResponse              │
         │  - content (text)       │
         │  - tool_calls (optional)│
         │  - finish_reason         │
         └───────────────────────────┘
                        │
                        │ 4. 处理响应
                        ▼
         ┌──────────────────────────────┐
         │  Orchestrator              │
         └────────────────┬─────────────┘
                        │
                        │ 5a. 如果 tool_calls → 执行工具
                        │ 5b. 否则 → 添加到历史
                        ▼
         ┌──────────────────────────────┐
         │  Tool Adapter             │
         └────────────────┬─────────────┘
                        │
                        │ 6. 转换 + 执行
                        ▼
         ┌──────────────────────────────┐
         │  OpenSandbox              │
         └────────────────┬─────────────┘
                        │
                        │ 7. 返回结果
                        ▼
         ┌──────────────────────────────┐
         │  Execution Results         │
         └───────────────────────────┘
                        │
                        │ 8. 格式化 + 更新历史
                        ▼
         ┌──────────────────────────────┐
         │  Orchestrator              │
         └────────────────┬─────────────┘
                        │
                        │ 更新 conversation_history
                        ▼
                    回到步骤 2（循环直到完成）
```

## 错误处理策略

### 1. 工具执行错误

```python
async def _execute_command(self, tool_call: ToolCall) -> ToolResult:
    try:
        result = await self.sandbox.commands.run(command)

        # 检查执行错误
        if result.error:
            return ToolResult(
                status=ToolStatus.ERROR,
                error=f"{result.error.name}: {result.error.value}",
                call_id=tool_call.call_id,
            )

        # 提取输出
        stdout = "\n".join([msg.text for msg in result.logs.stdout])
        stderr = "\n".join([msg.text for msg in result.logs.stderr])

        return ToolResult(
            status=ToolStatus.SUCCESS,
            output=stdout + ("\n" + stderr if stderr else ""),
            call_id=tool_call.call_id,
        )
    except Exception as e:
        return ToolResult(
            status=ToolStatus.ERROR,
            error=f"Execution failed: {str(e)}",
            call_id=tool_call.call_id,
        )
```

### 2. LLM API 错误

```python
async def run(self, user_message: str, max_steps: int = 10):
    try:
        response = await self.llm_client.chat(
            messages=self.conversation_history,
            tools=get_tool_definitions(),
        )
    except Exception as e:
        # LLM API 调用失败
        print(f"LLM API error: {e}")
        # 可以选择重试或失败任务
        raise
```

### 3. 超时和资源管理

```python
# 在 SandboxConfig 中设置超时
SandboxConfig(
    timeout=timedelta(minutes=10),  # 单个沙箱会话超时
)

# ConnectionConfig 中的请求超时
ConnectionConfig(
    request_timeout=timedelta(seconds=60),  # 单个请求超时
)
```

## 技术栈

| 组件 | 技术选择 |
|------|----------|
| Python 版本 | 3.10+ |
| 包管理 | uv / pip |
| OpenSandbox SDK | opensandbox>=0.1.0, opensandbox-code-interpreter>=0.1.0 |
| LLM 集成 | OpenAI API (支持兼容格式) |
| 异步框架 | asyncio |
| 配置管理 | Pydantic |
| 类型检查 | dataclass / typing |

## 项目结构

```
Agent2Sandbox/
├── agent2sandbox/              # 主包目录
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── orchestrator.py     # Agent 协调器（对话历史管理）
│   │   ├── state_manager.py    # 状态管理器
│   │   └── types.py            # 核心类型定义
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── tool_adapter.py     # 工具适配器（沙箱操作）
│   │   └── result_converter.py # 结果转换器（已废弃，功能合并）
│   ├── tools/
│   │   ├── __init__.py
│   │   └── definitions.py      # 工具定义
│   ├── llm/
│   │   ├── __init__.py
│   │   └── client.py           # LLM 客户端抽象
│   └── config/
│       ├── __init__.py
│       └── config.py           # 配置管理
├── test/                       # 测试目录
│   ├── test1-sandbox-interaction.py      # 基础沙箱交互测试
│   ├── test2-real-llm-integration.py  # LLM API 集成测试 ✅
│   ├── test3-agent-tasks.py               # Agent 任务测试 ✅
│   ├── test_sandbox_creation.py            # 沙箱创建测试 ✅
│   └── test_framework_basic.py           # 框架基础测试 ✅
├── pyproject.toml              # 项目配置
├── architecture.md            # 本文档
└── .env                     # 环境变量（gitignored）
```

## 扩展性设计

### 1. 多 LLM 支持

通过抽象 `LLMClient` 接口，支持多种 LLM 提供商：

- OpenAI（包括 GPT-4、GPT-3.5）
- DeepSeek（深度求索）
- Anthropic（Claude）
- 本地模型（Ollama、vLLM）

```python
# 切换不同的 LLM
from agent2sandbox.llm import OpenAIClient, AnthropicClient

# 使用 DeepSeek
llm_client = OpenAIClient.from_config(config)

# 使用 Claude（示例）
llm_client = AnthropicClient(api_key="...")
```

### 2. 自定义工具

允许注册自定义工具，扩展框架能力：

```python
from agent2sandbox.tools import register_tool

@register_tool({
    "name": "custom_analysis",
    "description": "Perform custom analysis",
    "parameters": {...}
})
async def custom_analysis(args):
    # 实现自定义逻辑
    pass
```

### 3. 多沙箱支持

架构设计支持同时管理多个沙箱实例，适用于并行任务场景。

### 4. 任务模式扩展

支持多种任务模式：
- 单轮任务：一次请求完成
- 多轮对话：持续的对话交互
- 自主迭代：Agent 主动探索和执行
- 工作流：预定义的多步骤流程

## 安全性考虑

### 1. 沙箱隔离
- 所有代码和命令在隔离的容器中执行
- 容器有资源限制（CPU、内存、网络）

### 2. 权限控制
- 沙箱资源限制（通过 SandboxConfig）
- 工具调用参数验证
- 文件系统访问限制

### 3. API 密钥管理
- 支持通过环境变量或 .env 文件配置
- .gitignore 确保 .env 不被提交到版本控制
- 运行时验证配置有效性

### 4. 输入验证
- 工具调用参数类型检查（通过 Pydantic）
- 必需参数验证
- 超时和重试机制

### 5. 错误处理
- 详细的错误信息返回给 LLM
- 异常捕获和日志记录
- 优雅的资源清理

## 性能优化

### 1. 并行工具执行
```python
# 多个工具调用可以并行执行
results = await asyncio.gather([
    execute_tool(tc1),
    execute_tool(tc2),
    execute_tool(tc3),
])
```

### 2. 连接复用
- OpenSandbox 连接复用
- CodeInterpreter 实例复用

### 3. 对话历史缓存
- 对话历史可以序列化保存
- 支持任务恢复和断点续传

### 4. 超时控制
- 单个请求超时控制
- 单个沙箱会话超时控制
- 最大步数限制

## 测试策略

### 1. 单元测试
- 框架基础测试（test_framework_basic.py）
- 工具适配器测试
- LLM 客户端测试

### 2. 集成测试
- LLM API 集成测试（test2-real-llm-integration.py）
- 沙箱交互测试（test1-sandbox-interaction.py）

### 3. 端到端测试
- Agent 任务测试（test3-agent-tasks.py）
  - 数据分析任务
  - 代码调试任务

### 4. 测试覆盖
- 正常流程测试
- 错误处理测试
- 边界条件测试
- 性能和负载测试

## 设计原则总结

1. **对话优先**：维护完整的对话历史，确保 LLM 上下文连续性
2. **工具抽象**：沙箱环境通过标准工具接口暴露，降低耦合
3. **状态透明**：Agent 不需要了解沙箱底层实现细节
4. **可扩展性**：支持多 LLM、多沙箱、自定义工具
5. **错误恢复**：完善的错误处理和日志记录
6. **资源管理**：自动化的沙箱生命周期管理和资源清理
7. **配置灵活**：支持多种配置方式，适配不同场景

## 与其他框架对比

### 特性对比

| 特性 | Agent2Sandbox | LangChain | AutoGPT |
|------|--------------|----------|----------|
| 对话历史管理 | ✅ 显式管理 | ⚠️ 隐式管理 | ❓ 未知 |
| 沙箱抽象 | ✅ 标准化工具 | ⚠️ 有限支持 | ❓ 未知 |
| LLM 抽象 | ✅ 统一接口 | ⚠️ 耦合特定 LLM | ❓ 未知 |
| 多沙箱支持 | ✅ 支持 | ❓ 未知 | ❓ 未知 |
| 自定义工具 | ✅ 支持 | ✅ 支持 | ✅ 支持 |
| 轻量级 | ✅ 是 | ⚠️ 较重 | ✅ 是 |

### 适用场景

**Agent2Sandbox 最适合：**
- 需要精细控制沙箱环境的任务
- 需要完整对话历史的场景
- 多轮交互的复杂任务
- 需要调试和观察执行过程的场景
- 教育和演示场景

**可能不适合：**
- 简单的单次 API 调用
- 只需要 LLM 不需要工具的场景
- 对实时性要求极高的场景

## 未来改进方向

### 1. 智能工具选择
- 基于 LLM 推荐选择最优工具
- 工具执行历史分析

### 2. 对话压缩
- 长对话历史的智能压缩
- 保留关键信息的摘要

### 3. 流式响应
- 支持 LLM 流式输出
- 实时进度反馈

### 4. 多沙箱编排
- 智能分配任务到不同沙箱
- 跨沙箱的文件共享

### 5. 任务模板库
- 预定义常用任务模板
- 快速任务启动

### 6. 可视化界面
- Web UI 展示对话历史
- 实时沙箱状态监控
- 交互式调试工具

### 7. 持久化存储
- 对话历史持久化
- 任务结果缓存
- 执行状态恢复

## 总结

Agent2Sandbox 是一个**以对话状态为核心的轻量级 Agent 框架**，通过维护完整的对话历史实现智能的多轮交互。其设计遵循以下核心原则：

1. **对话连续性**：确保 LLM 始终看到完整的上下文
2. **环境抽象**：沙箱通过标准工具接口暴露，降低耦合度
3. **状态管理**：自动化的生命周期管理和资源清理
4. **可扩展性**：支持多 LLM、多沙箱、自定义工具
5. **安全性**：完善的错误处理和资源限制

该框架特别适合：
- 需要精细控制沙箱环境的场景
- 多轮交互的复杂任务
- 教育和演示场景
- 需要调试和观察执行过程的场景

通过清晰的分层架构和标准化接口，Agent2Sandbox 提供了一个强大、灵活且易于扩展的 Agent 和沙箱交互解决方案。
