# Kelvin Specification

Kelvin is a personal AI chat and workflow tool for research, experimentation, development, and creative work. It works in any project directory, while keeping durable application data in standard XDG locations.

-----

## Philosophy

- **Bring the tool to the project** — Kelvin attaches to the current working tree instead of requiring a special master workspace
- **Filesystem as source of truth** — conversations, prompts, and project state live in plain files and directories
- **Append-only conversations** — conversation records are written once and never rewritten
- **Canonical data plus local aliases** — UUID-backed records for stability, human-readable symlinks for navigation
- **Simple context model** — a directory with `.kelvin/` is a Kelvin context
- **Human in the loop** — the model proposes, the human decides what runs

-----

## Storage Model

Kelvin uses XDG directories for global application storage.

### Global Paths

- `XDG_CONFIG_HOME/kelvin/`
  - configuration
- `XDG_DATA_HOME/kelvin/`
  - durable user data
- `XDG_STATE_HOME/kelvin/`
  - runtime state
- `XDG_CACHE_HOME/kelvin/`
  - disposable derived data

Typical defaults:

```text
~/.config/kelvin/
~/.local/share/kelvin/
~/.local/state/kelvin/
~/.cache/kelvin/
```

### What Lives Where

**Config**

- `~/.config/kelvin/config.yaml`

**Data**

- `~/.local/share/kelvin/convos/`
- `~/.local/share/kelvin/prompts/`

**State**

- `~/.local/state/kelvin/last_context`
- `~/.local/state/kelvin/history`

**Cache**

- indexes
- previews
- token counts
- any other rebuildable metadata

Conversation history is **data**, not cache.

-----

## Contexts

A **context** is a project directory marked by a local `.kelvin/` directory.

### Context Discovery

- Kelvin starts from `cwd`
- It walks upward to find the nearest ancestor containing `.kelvin/`
- That directory becomes the active context
- If no `.kelvin/` directory is found, Kelvin exits with an error
- `kelvin init` creates `.kelvin/` in `cwd`

### Local Context Files

Each context uses:

```text
project/
├── .injected
├── .kelvin/
│   ├── state.json
│   ├── local.injected
│   └── convos/
└── ...
```

### Local Context State

`./.kelvin/state.json`

```json
{
  "last_convo": "550e8400-e29b-41d4-a716-446655440000"
}
```

Rules:

- `last_convo` is a UUID, not a slug
- global state should stay minimal

### Global State

Global state is intentionally small:

- `last_context` — normalized absolute path to the last active context
- `history` — CLI readline history

-----

## Conversations

Conversations are stored canonically by UUID in XDG data storage.

### Canonical Store

```text
~/.local/share/kelvin/convos/
└── 550e8400-e29b-41d4-a716-446655440000/
    ├── 0001-meta
    ├── 0002-user
    ├── 0003-asst
    ├── 0004-tool
    └── ...
```

Each conversation directory is the durable source of truth.

### Local Aliases

Each context may expose human-readable symlinks:

```text
project/
└── .kelvin/
    └── convos/
        └── docker-networking -> ~/.local/share/kelvin/convos/550e8400-e29b-41d4-a716-446655440000/
```

Rules:

- symlink names are slugs, not identities
- multiple symlinks may point to the same conversation
- a conversation may appear in multiple contexts
- renaming a symlink does not modify the canonical conversation
- Kelvin only creates local aliases during `/convo new`
- Kelvin does not provide functionality to attach an existing convo to a context by alias in v1
- if the requested alias already exists, `/convo new` refuses to create the conversation

### Naming

- filenames are zero-padded sequence numbers plus a short suffix
- suffixes are `meta`, `user`, `asst`, `tool`
- convo files have **no extension**

Examples:

```text
0001-meta
0002-user
0003-asst
0004-tool
0005-meta
```

### File Kinds

All conversation files use the same file format:

- YAML frontmatter header
- optional raw body after the second `---`

Meta files do not have a `role`.

Transcript files (`user`, `asst`, `tool`) always have:

- `role`
- `timestamp`

Role values are:

- `user`
- `assistant`
- `tool`

Filename suffixes stay short (`asst`), but the `role` value is the full word (`assistant`).

### Conversation File Format

Example initial meta file:

```text
---
title: Docker Networking Deep Dive
uuid: 550e8400-e29b-41d4-a716-446655440000
timestamp: 2026-04-02T09:00:00Z
context: /home/val/src/project
model: gpt-4.1
endpoint: openai
fork_of: null
fork_at: null
prompts:
  - prompt: infra-engineer
---
```

Required fields in `0001-meta`:

- `title`
- `uuid`
- `timestamp`
- `context`
- `model`
- `endpoint`
- `fork_of`
- `fork_at`
- `prompts`

Prompt references use filenames/slugs. Kelvin assumes prompt files are stable in v1.

All conversation files start with `---`, then a YAML header, then a second `---`.

If the file has content after the second `---`, that content is the raw body.

Meta files typically have an empty body.

Example user file:

```text
---
role: user
timestamp: 2026-04-02T09:00:05Z
---
Let's talk about docker networking
```

Example assistant file:

```text
---
role: assistant
timestamp: 2026-04-02T09:00:08Z
---
Sure, let's start with the basics...
```

Example tool file:

```text
---
role: tool
timestamp: 2026-04-02T09:00:10Z
tool: shell
cmd: rg TODO .
---
{"success":true,"exit_code":0,"stdout":"README.md:12: TODO","stderr":""}
```

This is a Kelvin file format convention. Conversation files are not plain YAML documents.

### Replay Model

Kelvin supports faithful replay of:

- conversation messages
- prompt references
- model changes
- endpoint changes
- prompt add/drop changes
- injected file selection changes
- conversation switch events
- shell `!` events

Kelvin does **not** attempt faithful replay of historical injected file contents.

Injected files are live views of the working tree at send time. Conversation logs record which files were injected, not their exact historical contents.

This is context provenance, not bit-for-bit historical reconstruction.

### Forking

Forks are independent conversations with a backreference to a parent conversation.

```text
---
title: Docker Networking - Volume Focus
uuid: 7c9e4f21-b83a-42c1-...
timestamp: 2026-04-02T09:16:00Z
context: /home/val/src/project
model: gpt-4.1
endpoint: openai
fork_of: 550e8400-e29b-41d4-a716-446655440000
fork_at: 2026-04-02T09:15:00Z
prompts:
  - prompt: infra-engineer
---
```

Fork boundaries are timestamp-based.

### Fork Loading

To load a forked conversation:

1. Load the fork's `0001-meta`.
2. If `fork_of` is null, load the conversation normally.
3. If `fork_of` is set, load the parent conversation identified by that UUID.
4. Replay parent files in parent filename order.
5. Include parent events only up to `fork_at`.
6. Stop parent replay exactly at `fork_at`.
7. Then replay the fork's own files in fork filename order.

Rules:

- `fork_of` links to the parent conversation UUID
- `fork_at` is the cutoff point in the parent conversation
- parent replay is inclusive through `fork_at`
- events after `fork_at` in the parent are not visible in the fork
- nested forks recurse using the same rules

-----

## Prompts

Prompts are durable user data stored globally.

```text
~/.local/share/kelvin/prompts/
├── system/
├── templates/
└── workflows/
```

Each prompt file is a Markdown file with a `.md` extension and uses YAML frontmatter.

Example:

```yaml
---
title: Infrastructure Engineer
type: system
model: claude-sonnet-4
version: 1.2
timestamp: 2026-04-01T00:00:00Z
tags: [infra, ops]
status: active
supersedes: null
---

Prompt body starts here...
```

Rules:

- prompts are global in v1
- prompt filenames are assumed unique across all prompt directories in v1
- users refer to prompts by basename without the `.md` extension
- Kelvin resolves prompt references by locating the unique matching filename in the global prompt directories
- prompt references are stored in conversation meta
- resuming a conversation uses the recorded prompt filenames
- starting a fresh conversation uses current global prompt files

-----

## Injected Files

Each context may define injected files using two plain text files:

- `./.injected` — user-edited defaults
- `./.kelvin/local.injected` — Kelvin-managed local overlay

Both files use the same line-based format.

### File Format

Rules:

- blank lines are ignored
- lines starting with `#` are comments
- paths are relative to the context root
- `path/to/file` means include
- `-path/to/file` means exclude
- lines are processed top to bottom
- later lines win
- if a real path begins with `-`, it must be written as `./-name`

Example `.injected`:

```text
# Core docs
README.md
docs/architecture.md
```

Example `local.injected`:

```text
notes/todo.md
-docs/architecture.md
./-oddly-named-file.txt
```

Rules by file:

- `.injected` is user-owned project config
- `local.injected` is Kelvin-managed local overlay
- negative lines are allowed in both files because the grammar is identical
- users are discouraged from using exclusions in `.injected`
- Kelvin may warn when it sees exclusions in `.injected`

### Effective Injected Set

Before each send, Kelvin rebuilds the effective injected file set from:

1. `.injected`
2. `local.injected`

Normalization rules:

- relative paths are resolved against the context root
- absolute paths are preserved as absolute paths
- normalized paths should not retain `../` segments
- duplicate paths collapse to one effective entry
- missing selected files are warned and skipped
- Kelvin does not restrict injected paths to the context; user-specified paths are trusted in v1

Injected files are read fresh from disk at send time.

### Logging

If the effective injected set changes between sends, Kelvin appends a meta event.

Example:

```yaml
timestamp: 2026-04-02T09:15:00Z
event: injected_set_changed
reason: local_injected_changed
injected:
  - README.md
  - notes/todo.md
added:
  - notes/todo.md
removed:
  - docs/architecture.md
```

Kelvin records:

- the resulting full injected set
- the added paths
- the removed paths

Kelvin does not record injected file contents.

### Prompt Format

Injected files are wrapped in XML tags in the prompt:

```xml
<injected file="README.md" mode="644">
... file contents ...
</injected>
```

`mode` is read from the filesystem at prompt-build time. It is a hint to the model about whether the file is expected to be mutable. It is not a security boundary.

-----

## CLI

Kelvin is a readline-style CLI chat tool.

### Core Behavior

- active context comes from the nearest `.kelvin/`
- last active context is restored from global state if still valid
- per-context resume uses `./.kelvin/state.json`
- conversations are persisted in the canonical UUID store
- local aliases live in `./.kelvin/convos/`

### Commands

Conversation:

```text
/convo [name]
/convo list
/convo new [name]
/convo fork [name]
```

Navigation:

```text
/switch [path]
/switch list
```

Prompts:

```text
/prompt
/prompt add [slug]
/prompt drop [slug]
```

Injection:

```text
/inject [file]
/inject list
/inject drop [file]
/inject clear
```

Model:

```text
/model [name]
/model list
```

Info:

```text
/show config
/show status
/show history
/status
/history
/help
/quit
```

Shell:

```text
!<command>
```

### Command Line Parsing

Kelvin uses `docopt-ng` for command line argument parsing.

### Shell Behavior

There are two distinct shell behaviors:

- `!<command>` — user-entered shell escape
- `shell` tool — model-invoked tool

#### `!<command>`

`!<command>` runs in the active context directory using a fresh non-interactive shell.

Kelvin executes it as:

```text
bash -c "<command>"
```

Kelvin records `!<command>` as a meta event only. It does not store command output in the conversation log in v1.

Example:

```yaml
timestamp: 2026-04-02T09:20:00Z
event: shell_bang
cmd: git status --short
cwd: /home/val/src/project
exit_code: 0
```

#### `shell` Tool

The only model-facing tool in v1 is `shell`.

The model provides only the command string. Kelvin decides how to execute it.

Model-facing input shape:

```yaml
tool: shell
input:
  cmd: rg TODO .
```

Kelvin executes it as:

```text
bash -c "<cmd>"
```

The tool result body may be raw JSON text.

Tool result shape:

- success result:
  - `{"success":true,"exit_code":0,"stdout":"...","stderr":"..."}`
- tool-call failure result:
  - `{"success":false,"error":"..."}`

In v1, a nonzero command exit code is still a successful tool call if Kelvin executed the command and captured the result.

Example tool transcript file:

```text
---
role: tool
timestamp: 2026-04-02T09:21:00Z
tool: shell
cmd: rg TODO .
---
{"success":true,"exit_code":0,"stdout":"README.md:12: TODO","stderr":""}
```

### Meta Events

Kelvin appends meta files whenever conversation-relevant state changes.

Examples include:

- model changed
- endpoint changed
- prompt added
- prompt dropped
- injected set changed
- switched away from a conversation
- shell `!` executed

Example model change:

```yaml
timestamp: 2026-04-02T09:12:00Z
event: model_changed
model: llama3
endpoint: ollama
```

Example prompt add:

```yaml
timestamp: 2026-04-02T09:13:00Z
event: prompt_added
prompt: researcher
```

Example switched away:

```yaml
timestamp: 2026-04-02T09:14:00Z
event: switched_away
to_context: /home/val/src/other-project
to_convo: 7c9e4f21-b83a-42c1-...
```

-----

## Config

Global config lives at:

```text
~/.config/kelvin/config.yaml
```

Example:

```yaml
default_model: firmen102/qwen3.5-27b
default_endpoint: ollama
endpoints:
  openai:
    url: https://api.openai.com/v1
    key_env: OPENAI_API_KEY
  ollama:
    url: http://localhost:11434/v1
    key_env: null
  vllm:
    url: http://localhost:8000/v1
    key_env: null
```

### API

For remote OpenAI-backed chat, Kelvin uses the OpenAI Chat/Conversation API.

This is the default cloud conversation transport in v1.

-----

## Git

Kelvin should recommend adding `.kelvin/` to `.gitignore`.

`.injected` is user-owned and lives outside `.kelvin/`, so the user may choose whether to commit it.

-----

## Permissions

Permissions are a useful convention and an active Kelvin behavior.

Conventions:

- conversation files are append-only
- each conversation file is written once
- after write, Kelvin makes the file read-only
- mutable working files remain writable during active work

Default mode conventions:

- frozen files: `444`
- active files: `644`
- directories: `755`

Kelvin should actively apply read-only mode to conversation files after writing them.

`chmod 444` is a helpful immutability guardrail, but Kelvin should not pretend file mode bits alone are a complete authorization system.

-----

## Deferred Decisions

- whether to introduce stronger schema validation for transcript headers and tool result JSON
- whether to split large tool results into separate files later
- whether large shell output should be truncated, summarized, or sharded in a future format revision
- whether to add functionality to link existing conversations into new contexts
- whether prompt versioning and prompt snapshots should be added in a future format revision
