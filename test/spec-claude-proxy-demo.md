# Claude-Code via LLM-Proxy Demo Spec (v0.1)

## Objective
Validate an end-to-end path where sandbox runtime accesses model capabilities only through local `LLM-Proxy`, while proxy records session trajectory and task logs.

## Scope
- In scope:
  - local proxy listening endpoint
  - centralized model routing settings from `config/llmproxy-cfg.yaml`
  - sandbox command execution in `code-interpreter:v1.0.1`
  - per-session trajectory jsonl output
- Out of scope:
  - remote MCP/local MCP runtime integration
  - artifact upload channel to external storage
  - k8s deployment and distributed monitoring

## Test Case
### ID
`TC_CLAUDE_PROXY_E2E_SMOKE`

### Inputs
- Task file: `tasks/claude_proxy_demo.yaml`
- Env file: `agent2sandbox/.env`
- Proxy cfg file: `config/llmproxy-cfg.yaml`
- Sandbox cfg file: `config/sandbox-server-cfg.yaml`
- Sandbox image: `sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.1`
- Entrypoint: `/opt/opensandbox/code-interpreter.sh`

### Steps
1. Start local `LLM-Proxy` at `127.0.0.1:18080`.
2. Read routing config from `config/llmproxy-cfg.yaml` and resolve key refs from `.env`.
3. Read sandbox server config from `config/sandbox-server-cfg.yaml`.
4. Create sandbox and inject:
   - `ANTHROPIC_BASE_URL=http://127.0.0.1:18080`
   - `ANTHROPIC_AUTH_TOKEN=<session_token>`
   - `ANTHROPIC_MODEL=<task.model>`
5. Register `(session_token, sandbox_id, task_name)` into proxy.
6. Run task command in sandbox:
   - `claude --version`
   - `claude "Reply with exactly: A2S_OK_20260211 and nothing else."`
7. Read `/tmp/claude_result.txt`.
8. Verify trajectory log file exists: `logs/trajectory/<session>.jsonl`.
9. Cleanup sandbox and stop proxy.

### Expected Result
- command runtime has no error
- output includes `A2S_OK_20260211` (stdout or artifact)
- if route is `anthropic -> anthropic`, proxy must passthrough request/response without schema conversion
- if route is `anthropic -> openai`, proxy must convert schema before upstream call
- trajectory file exists and includes:
  - `session_registered`
  - `route_selected`
  - `anthropic_request`
  - `anthropic_passthrough` or `anthropic_converted_response`
  - `task_command_finished`
- proxy accepts Anthropic `stream=false/true` request mode

## Failure Classification
- `sandbox_create_error`: OpenSandbox create/entrypoint failure
- `proxy_bind_error`: local proxy port bind failure
- `upstream_error`: upstream API non-2xx
- `runtime_error`: task command execution error in sandbox
- `artifact_read_error`: artifact missing or unreadable
