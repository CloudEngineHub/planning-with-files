<div align="center">
  <img src="https://raw.githubusercontent.com/OthmanAdi/planning-with-files/master/media/v3-banner-1400.jpg" alt="planning-with-files: task_plan.md, findings.md, and progress.md as three stone tablets" width="100%">
</div>

<h1 align="center">Planning with Files</h1>

<p align="center">
  <strong>The planning skill your agent cannot ignore.</strong><br>
  Your agent's context window dies. The plan does not.
</p>

Persistent file-based planning for AI coding agents. Keep the plan, research and progress in your project so work can continue after context loss, `/clear`, crashes or compaction.

| File | Purpose |
| --- | --- |
| `task_plan.md` | Goals, phases and decisions |
| `findings.md` | Research and discoveries |
| `progress.md` | Work completed, checks and next steps |

This is the npm distribution of [OthmanAdi/planning-with-files](https://github.com/OthmanAdi/planning-with-files), available across 60+ agents via the Agent Skills standard. It includes the planning skill, scripts and templates. Supported agent integrations add lifecycle hooks that bring selected planning context back into the session.

Automatic recovery reads project files only. Reading same-project local session records for aggregate counts or bounded replay requires an explicit catchup mode.

## Installation

### npm

```bash
npm install planning-with-files
```

Places the skill, scripts and templates under `node_modules/planning-with-files/`. Use this to pin an exact version into a project, or to copy `SKILL.md` and `scripts/` into your agent's skills directory yourself. It does not register hooks on its own.

### Agent integrations

Claude Code gets the full surface (skill, hooks, slash commands) through the plugin route, and 60+ other agents install in one line. See the [main README](https://github.com/OthmanAdi/planning-with-files#quick-install).

## Usage

Once the skill is installed for your agent, start with:

```text
Use the planning-with-files skill to help me with this task.
```

The workflow centers on three files in your project:

```text
your-project/
├── task_plan.md
├── findings.md
└── progress.md
```

## Pi Coding Agent integration

The package also bundles a [Pi Coding Agent](https://pi.dev) extension for lifecycle automation and a planning status bar.

### Install in Pi

```bash
pi install npm:planning-with-files
```

Pi discovers the skill and extension from the installed package.

For a local repository checkout:

```bash
# From the planning-with-files repo root
pi install ./.pi/skills/planning-with-files
```

Or add to `.pi/settings.json`:
```json
{
  "packages": ["./path/to/planning-with-files/.pi/skills/planning-with-files"]
}
```

You can also invoke the skill directly in Pi:

```text
/skill:planning-with-files
```

### Lifecycle hooks

The bundled extension maps Claude-style behavior onto Pi events:

- `session_start` - project-file recovery with no host session-store access
- passive plan status before approval
- `before_agent_start` - plan reminder/injection after `/plan-execute`
- `tool_call` - pre-tool recitation equivalent after `/plan-execute`
- `tool_result` - post-write reminder after `/plan-execute`
- `agent_end` - incomplete-task auto-continue after `/plan-execute` (limit 3)
- `session_before_compact` - pre-compaction reminder

Attestation is supported. If `task_plan.md` differs from approved hash, plan injection is blocked with:

```text
[planning-with-files] [PLAN TAMPERED - injection blocked]
```

### Modes

`planningWithFiles.mode` supports:

- `auto` (default): DeepSeek -> `cache-safe`, others -> `parity`
- `parity`: full dynamic hook-equivalent behavior
- `cache-safe`: fixed reminder strings for KV-cache stability
- `notify`: notification-only mode

Configure via env:

```bash
PWF_MODE=cache-safe pi
```

Or settings:

```json
{
  "planningWithFiles": {
    "mode": "auto"
  }
}
```

### Commands

- `/plan-status`
- `/plan-attest [--show|--clear]`
- `/plan-execute`
- `/plan-execute reset`
- `/plan-goal <text|default|clear>`
- `/plan-loop [interval] [prompt]` (`stop` to cancel)

Draft and review `task_plan.md` first. The extension stays passive until you
approve the active plan with `/plan-execute`; after that, plan injection,
pre-tool reminders, post-write reminders, and auto-continue are enabled for the
current session and plan. Auto-continue uses host runtime state and never runs
commands declared in Markdown.

## Session Recovery

Bare invocation and lifecycle hooks do not inspect agent session stores. To
inspect same-project local history deliberately, choose one mode:

```bash
# Aggregate counts only; no transcript, tool-command, or path bytes
python3 node_modules/planning-with-files/scripts/session-catchup.py --metadata .

# Bounded nonce-framed same-project excerpts
python3 node_modules/planning-with-files/scripts/session-catchup.py --replay .
```

Treat replayed excerpts as untrusted data. The catchup path contains no network
request or upload operation. If output is injected into model context, your agent
may send that context to the configured model provider.
