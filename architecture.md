# Agent2Sandbox 设计文档（精简版）

> 目标：移除旧 Agent 模块，引入任务定义、LLM-Proxy 与 MCP 分层；demo 阶段只做接口与配置透传，不实现监控、交付件与 MCP 通信细节。

## 1. 核心目标
- **任务定义**：`tasks/` 目录以 JSON/YAML 描述任务（镜像、sandbox_entrypoint、task_command、LLM、MCP、目标、结束条件、交付件）。
- **LLM-Proxy 中心化**：对齐 OpenAI/Anthropic API（非流式），统一路由与鉴权，并按 `sandbox_id` 归档对话历史。
- **MCP 分层**：remote / local / internet 三类接口，demo 阶段仅透传配置。
- **运行时解耦**：sandbox 镜像自带 agent/CLI，容器内直接调用 LLM-Proxy。

## 2. Demo 非目标
- 交付件回传不实现（仅保留任务字段）。
- 监控与失败策略不实现（仅保留接口占位）。
- MCP 通信不实现（仅保留配置结构）。

## 3. 架构总览
```
Task Runner/Launcher
  ├─ 读取 tasks/ 配置
  ├─ 创建 OpenSandbox
  ├─ 透传 LLM/MCP/ENV/sandbox_entrypoint
  ├─ 透传 task_command 到容器内
  └─ 预留监控接口

Sandbox Runtime (code-interpreter 镜像)
  ├─ sandbox_entrypoint 作为容器主进程启动
  └─ task_command 在容器内执行（由启动脚本或 agent 触发）
        └─ 调用 LLM-Proxy (OpenAI/Anthropic 兼容)

LLM-Proxy
  ├─ OpenAI/Anthropic 兼容 API
  ├─ 统一鉴权/路由
  ├─ 按 sandbox_id 归档历史
  └─ 存储：JSON/JSONL → 可演进 SQLite/PostgreSQL

MCP Services (占位)
  ├─ Remote MCP (集群共享)
  ├─ Local MCP (sandbox 内)
  └─ Internet MCP (可选)
```

## 4. 任务定义（示例）
```yaml
name: demo-task
image: sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.1
sandbox_entrypoint:
  - /opt/opensandbox/code-interpreter.sh
task_command:
  - bash
  - -lc
  - "claude 'Compute 1+1.'"
llm:
  provider: openai  # or anthropic
  proxy_url: http://llm-proxy:8000
  model: gpt-4o-mini
  api_key_ref: ENV:LLM_PROXY_API_KEY
mcp:
  remote: []
  local: []
  internet: []
goal: "完成特定任务描述"
finish_condition:
  type: manual
artifacts:
  - path: /tmp/output.txt
```

## 5. 字段语义说明
- `sandbox_entrypoint`：**传给 OpenSandbox 的 user entrypoint**，容器启动时执行（必填）。
- `task_command`：任务启动指令，由容器内脚本/agent 触发执行；可选。

## 6. 组件职责
- **Task Runner/Launcher**：解析任务定义 → 创建 sandbox → 透传配置 → 启动 sandbox_entrypoint。
- **LLM-Proxy**：兼容 OpenAI/Anthropic（非流式），记录对话历史，未来可切换数据库。
- **MCP 模块**：统一配置结构，后续落地 gRPC over HTTP/2。
- **监控模块（占位）**：定义心跳/超时/状态检查接口。

## 7. Demo 镜像与 entrypoint
- 镜像：`sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.1`
- entrypoint：`/opt/opensandbox/code-interpreter.sh`
- claude-code 示例参考：`OpenSandbox/examples/claude-code/README.md`

## 8. 演进路径（简）
1) 任务定义 + LLM-Proxy 基础 API（非流式）。
2) Launcher 读取任务 → 启动 sandbox → 容器内执行 task_command → 调用 LLM-Proxy。
3) 引入 MCP 实现与监控/交付件机制。
