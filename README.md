# Agent2Sandbox

Agent2Sandbox 是一个面向 OpenSandbox 的轻量级 Demo 方案：通过统一的任务定义与本地 LLM-Proxy，把 sandbox 内的 LLM 调用全部汇聚到代理层，便于路由与日志留存。

## 目标与现状
- 以 `tasks/` 的 YAML/JSON 任务定义驱动 sandbox 运行。
- 本地 `LLM-Proxy` 负责路由与鉴权，记录对话日志。
- MCP / 监控 / 交付件机制为占位设计，demo 阶段不实现。

## 核心约束
- **不做 OpenAI/Anthropic 互转**：下游请求协议必须与 `route.upstream_provider` 一致，否则返回 `400 provider_mismatch`。
- **日志保留原始协议格式**：OpenAI 请求/响应以 OpenAI 结构保存，Anthropic 亦同。

## 目录结构
- `agent2sandbox/`：LLM-Proxy 与 demo runner 实现
- `config/`：本地配置（`llmproxy-cfg.yaml`、`sandbox-server-cfg.yaml`）
- `tasks/`：任务定义 YAML/JSON
- `test/`：可运行的测试脚本
- `logs/trajectory/`：按 session 归档的请求/响应日志

## LLM-Proxy 路由配置
编辑 `config/llmproxy-cfg.yaml`，并确保下游 `model` 与 `routes[].name` 匹配。

要点：
- 下游请求路径决定协议：
  - Anthropic: `/v1/messages`、`/v1/message`、`/messages`
  - OpenAI: `/v1/chat/completions`、`/chat/completions`
- `routes[].upstream.provider` 必须和下游协议一致。
- `routes[].upstream.upstream_model_name` 为上游真实模型名。

示例：
```yaml
version: 1
defaults:
  timeout_seconds: 120

routes:
  - name: deepseek-openai
    upstream:
      provider: openai
      base_url: https://api.deepseek.com
      upstream_model_name: deepseek-reasoner
      api_key_ref: ENV:DEEPSEEK_API_KEY

  - name: deepseek-anthropic
    upstream:
      provider: anthropic
      base_url: https://api.deepseek.com/anthropic
      upstream_model_name: deepseek-reasoner
      api_key_ref: ENV:DEEPSEEK_API_KEY
```

## 日志格式
每个 session 一个目录：`logs/trajectory/<session>/`，并按请求对落盘。

- `<timestamp>-req.json`
- `<timestamp>-assistant.json`

过滤逻辑：
- 首条 `user` 内容为 `warmup` 会跳过
- `system` 字段包含 `summarize this coding conversation` / `analyze if this message indicates a new conversation topic` 会跳过

## 启动 LLM-Proxy
```bash
cd /Users/chenxi/Desktop/WorkPlace/agent2env/Agent2Sandbox
uv run test/test3-llmproxy-standalone.py \
  --cfg-file config/llmproxy-cfg.yaml \
  --host 127.0.0.1 \
  --port 18080 \
  --log-dir logs/trajectory
```

## Claude-Code 使用（Anthropic）
```bash
export ANTHROPIC_BASE_URL="http://127.0.0.1:18080"
export ANTHROPIC_AUTH_TOKEN="session-claude-001"
export ANTHROPIC_MODEL="deepseek-anthropic"
claude
```

## Qwen-Agent 使用（OpenAI）
Qwen-Agent 会调用 OpenAI ChatCompletions，`model_server` 需要指向代理地址：
```python
llm_cfg = {
    'model': 'deepseek-openai',
    'model_server': 'http://127.0.0.1:18080',
    'api_key': 'session-openai-3',
}
```

## 测试脚本
- `test/test1-sandbox-interaction.py`: OpenSandbox 连接性检查
- `test/test2-claude-proxy-demo.py`: Claude-Code + LLM-Proxy E2E
- `test/test3-llmproxy-standalone.py`: 单独启动 LLM-Proxy

## 设计文档
- `architecture.md`：精简设计说明（已与当前实现对齐）
