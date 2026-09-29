workspace "MewCode" "Evidence-backed C4 model of MewCode, a terminal AI coding assistant (Python + Textual). Current state, derived from code inspection on 2026-09-28." {
    !identifiers hierarchical

    model {
        # ---- People ----
        dev = person "Developer" "Runs MewCode from a terminal to explore, edit, and reason about a codebase interactively."

        # ---- External systems ----
        automation = softwareSystem "Script or Service Caller" "Uses the documented -p command or Runtime HTTP API to submit non-interactive agent runs." {
            tags "External"
        }
        anthropic = softwareSystem "Anthropic API" "Claude models. Messages API with streaming and prompt caching." {
            tags "External"
        }
        openai = softwareSystem "OpenAI / Compatible API" "OpenAI and OpenAI-compatible models (Responses/Chat style)." {
            tags "External"
        }
        mcpServers = softwareSystem "MCP Tool Servers" "External Model Context Protocol servers exposing additional tools over stdio or HTTP." {
            tags "External"
        }
        workspaceRepo = softwareSystem "Local Workspace & Git Repo" "The user's project files and git repository that MewCode reads, edits, and runs shell/git commands against." {
            tags "External"
        }

        # ---- MewCode system ----
        mewcode = softwareSystem "MewCode" "Terminal AI coding assistant. Multi-provider LLM agent with tools, MCP, sub-agents, teams, skills, permissions, and session persistence." {

            tui = container "CLI & TUI Application" "mewcode command: interactive Textual TUI, plus -p one-shot headless execution. Wires config, permissions, tools, agents, teams, and the Agent Engine." "Python / Textual"

            server = container "Runtime Server" "mewcode-server command: FastAPI HTTP/SSE service for persistent agent runs (submit, query, cancel, stream events, replay/resume)." "Python / FastAPI / uvicorn" {
                serverMain = component "Server Entrypoint" "Parses --host/--port (default 127.0.0.1:8765), loads config, builds the runtime, and serves the app via uvicorn." "runtime/server.py"
                httpAdapter = component "HTTP Adapter" "FastAPI app exposing POST /v1/runs, GET /v1/runs/{id}, POST .../cancel, GET .../events (SSE). FastAPI imported lazily (optional 'server' extra)." "runtime/http.py"
                bootstrap = component "Runtime Bootstrap" "build_runtime(): wires agent_factory, conversation_factory, conversation_saver and RunStore from the same config/provider/permissions/tools as the CLI." "runtime/bootstrap.py"
                runtimeService = component "AgentRuntime Service" "Durable run orchestration: submit, execute with retry/timeout, cancel, emit events, subscribe (replay + live), recover after restart. No Textual/FastAPI dependency." "runtime/service.py"
                runStore = component "RunStore" "Append-only event store + JSON run snapshots, thread-locked, written under .mewcode/runs/." "runtime/store.py"
                runModels = component "Run Models" "AgentRun, RunEvent, RunStatus dataclasses with (de)serialization." "runtime/models.py"
            }

            engine = container "Agent Engine" "Core, UI-independent agent runtime: the prompt -> LLM -> tool loop, tool dispatch, context compaction, sub-agents, teams, memory, and permissions." "Python" {
                agentLoop = component "Agent Loop" "Drives run_to_completion: builds prompt, streams LLM output, dispatches tool calls, injects notifications/reminders." "agent.py"
                llmClient = component "LLM Client" "Provider adapters (Anthropic / OpenAI / OpenAI-compat), streaming, error mapping, prompt caching, context-window resolution." "client.py"
                prompts = component "Prompt Builder" "Builds the system prompt, environment context, and plan-mode reminders." "prompts.py"
                toolSystem = component "Tool System" "Tool registry + built-in tools: bash, read/edit/write file, glob, grep, tasks, ask-user, load-skill, agent/team/DAG tools." "tools/"
                mcpIntegration = component "MCP Integration" "Connects configured MCP servers and wraps their tools into the registry." "mcp/"
                subagents = component "Sub-agent System" "Agent loader, background task manager, and trace tree for Explore / Plan / General-purpose / Verification sub-agents." "agents/"
                teams = component "Agent Teams" "Coordinator mode, teammates, mailbox, shared tasks, and DAG orchestration (depends_on, parallel ready nodes)." "teams/"
                permissions = component "Permission System" "Permission modes, rule engine, dangerous-command detection, and path sandbox gating every tool call." "permissions/"
                contextMgr = component "Context Manager" "Tracks context-window usage and compacts long conversations." "context/"
                skills = component "Skill System" "Skill loader/executor and built-in skill packs (commit, review, test, backend-interview)." "skills/"
                hooks = component "Hook Engine" "Lifecycle hooks (startup/shutdown) and tool-gating hooks with conditions/executors." "hooks/"
                memory = component "Memory System" "User/project/feedback memory recall and session persistence across conversations." "memory/"
            }

            stateStore = container "State Store (.mewcode/)" "File-based state: config.yaml, permissions.yaml, session records, run snapshots (<run>.json) and event logs (<run>.events.jsonl), dag-runs, and memory files." "File system (YAML / JSON / JSONL)" {
                tags "Database"
            }
        }

        # ---- Relationships: system context ----
        dev -> mewcode "Uses via the terminal (interactive TUI or -p one-shot)"
        automation -> mewcode "Submits agent runs (one-shot CLI or HTTP runs API)" "CLI / HTTP / SSE"
        mewcode -> anthropic "Sends conversation, streams completions" "HTTPS"
        mewcode -> openai "Sends conversation, streams completions" "HTTPS"
        mewcode -> mcpServers "Discovers and invokes external tools" "stdio / HTTP"
        mewcode -> workspaceRepo "Reads/edits files; runs git and shell commands" "file / process"

        # ---- Relationships: container level ----
        dev -> mewcode.tui "Runs the interactive TUI"
        automation -> mewcode.server "POST /v1/runs, GET status, cancel, SSE events" "HTTP / SSE"
        mewcode.tui -> mewcode.engine "Drives the agent loop in-process"
        mewcode.server -> mewcode.engine "Builds and runs agents via runtime.bootstrap"
        mewcode.server -> mewcode.stateStore "Writes run snapshots and event logs (.mewcode/runs)" "file"
        mewcode.engine -> mewcode.stateStore "Persists sessions, memory, and run/DAG state" "file"
        mewcode.engine -> anthropic "Streams completions (anthropic protocol)" "HTTPS"
        mewcode.engine -> openai "Streams completions (openai / compat protocol)" "HTTPS"
        mewcode.engine -> mcpServers "Invokes wrapped MCP tools" "stdio / HTTP"
        mewcode.engine -> workspaceRepo "Reads/edits files; runs git and shell commands" "file / process"

        # ---- Relationships: components inside the Agent Engine ----
        mewcode.engine.agentLoop -> mewcode.engine.prompts "Builds system prompt and environment context"
        mewcode.engine.agentLoop -> mewcode.engine.llmClient "Sends conversation, streams tokens/tool calls"
        mewcode.engine.agentLoop -> mewcode.engine.toolSystem "Dispatches tool calls"
        mewcode.engine.agentLoop -> mewcode.engine.permissions "Checks permission before executing a tool"
        mewcode.engine.agentLoop -> mewcode.engine.contextMgr "Tracks usage and compacts context"
        mewcode.engine.agentLoop -> mewcode.engine.hooks "Fires lifecycle and tool-gating hooks"
        mewcode.engine.agentLoop -> mewcode.engine.memory "Recalls memory and persists sessions"
        mewcode.engine.agentLoop -> mewcode.engine.skills "Loads and executes skill packs"
        mewcode.engine.toolSystem -> mewcode.engine.mcpIntegration "Exposes MCP-provided tools in the registry"
        mewcode.engine.toolSystem -> mewcode.engine.subagents "AgentTool spawns sub-agents"
        mewcode.engine.toolSystem -> mewcode.engine.teams "TeamCreate / DAG tools orchestrate teammates"
        mewcode.engine.subagents -> mewcode.engine.agentLoop "Sub-agents run nested agent loops"
        mewcode.engine.teams -> mewcode.engine.subagents "Teammates are managed agents"
        mewcode.engine.llmClient -> anthropic "Anthropic protocol" "HTTPS"
        mewcode.engine.llmClient -> openai "OpenAI / compat protocol" "HTTPS"
        mewcode.engine.mcpIntegration -> mcpServers "Connects and wraps external tools" "stdio / HTTP"
        mewcode.engine.toolSystem -> workspaceRepo "bash / read / edit / write / glob / grep" "file / process"
        mewcode.engine.memory -> mewcode.stateStore "Reads/writes memory and session files" "file"

        # ---- Relationships: components inside the Runtime Server ----
        automation -> mewcode.server.httpAdapter "POST /v1/runs; GET .../events (SSE)" "HTTP / SSE"
        mewcode.server.serverMain -> mewcode.server.bootstrap "build_runtime(config)"
        mewcode.server.serverMain -> mewcode.server.httpAdapter "create_app(runtime); serves via uvicorn"
        mewcode.server.httpAdapter -> mewcode.server.runtimeService "submit / get / cancel / subscribe"
        mewcode.server.bootstrap -> mewcode.server.runtimeService "Constructs with factories + RunStore"
        mewcode.server.runtimeService -> mewcode.server.runStore "Saves snapshots; appends/reads events"
        mewcode.server.runtimeService -> mewcode.server.runModels "Uses AgentRun / RunEvent / RunStatus"
        mewcode.server.runStore -> mewcode.server.runModels "Serializes AgentRun / RunEvent"
        mewcode.server.runtimeService -> mewcode.engine "Runs agent.run_to_completion via agent_factory"
        mewcode.server.bootstrap -> mewcode.engine "Creates an Agent per run/retry (factory)"
        mewcode.server.runStore -> mewcode.stateStore "Writes .mewcode/runs/<id>.json + <id>.events.jsonl" "file"
        mewcode.server.bootstrap -> mewcode.stateStore "Resumes/saves conversation sessions" "file"
    }

    views {
        systemContext mewcode "SystemContext" "Big picture: who uses MewCode and which external systems it depends on." {
            include *
            autoLayout lr
        }

        container mewcode "Containers" "Runtime/deployable units inside MewCode and the state they persist." {
            include *
            autoLayout tb
        }

        component mewcode.engine "AgentEngineComponents" "Internal components of the Agent Engine container and how the loop collaborates." {
            include *
            autoLayout tb
        }

        component mewcode.server "RuntimeServerComponents" "Internal components of the Runtime Server: HTTP/SSE adapter, runtime bootstrap, durable run service, and event store." {
            include *
            autoLayout tb
        }

        styles {
            element "Person" {
                shape person
                background #08427b
                color #ffffff
            }
            element "External" {
                background #999999
                color #ffffff
            }
            element "Database" {
                shape cylinder
                background #2e7d32
                color #ffffff
            }
            element "Software System" {
                background #1168bd
                color #ffffff
            }
            element "Container" {
                background #438dd5
                color #ffffff
            }
            element "Component" {
                background #85bbf0
                color #000000
            }
        }
    }
}
