# Claude-Code via LLM-Proxy Demo Spec (v0.1)

## Objective
Validate an end-to-end path where sandbox runtime accesses model capabilities only through local `LLM-Proxy`, while proxy records session trajectory and task logs.

## Scope
- In scope:
  - local proxy listening endpoint
  - upstream model settings from `agent2sandbox/.env`
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
- Sandbox image: `sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.1`
- Entrypoint: `/opt/opensandbox/code-interpreter.sh`

### Steps
1. Start local `LLM-Proxy` at `127.0.0.1:18080`.
2. Read upstream config from `agent2sandbox/.env` (`BASE_URL/API_KEY/MODEL_NAME`).
3. Create sandbox and inject:
   - `ANTHROPIC_BASE_URL=http://127.0.0.1:18080`
   - `ANTHROPIC_AUTH_TOKEN=<session_token>`
   - `ANTHROPIC_MODEL=<task.model>`
4. Register `(session_token, sandbox_id, task_name)` into proxy.
5. Run task command in sandbox:
   - `claude --version`
   - `claude "Reply with exactly: A2S_OK_20260211 and nothing else."`
6. Read `/tmp/claude_result.txt`.
7. Verify trajectory log file exists: `logs/trajectory/<session>.jsonl`.
8. Cleanup sandbox and stop proxy.

### Expected Result
- command runtime has no error
- output includes `A2S_OK_20260211` (stdout or artifact)
- trajectory file exists and includes:
  - `session_registered`
  - `anthropic_request`
  - `anthropic_response`
  - `task_command_finished`
- proxy accepts Anthropic `stream=false/true` request mode

## Failure Classification
- `sandbox_create_error`: OpenSandbox create/entrypoint failure
- `proxy_bind_error`: local proxy port bind failure
- `upstream_error`: upstream API non-2xx
- `runtime_error`: task command execution error in sandbox
- `artifact_read_error`: artifact missing or unreadable
