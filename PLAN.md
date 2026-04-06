# ~/lab Specification

A personal AI-powered lab environment for research, experimentation, development, and creative work. Designed to be navigated by both humans and AI agents.

-----

## Philosophy

- **Filesystem as database** — markdown files, YAML, and directory structure replace any external database
- **Append-only by default** — records are written once and locked; history is never rewritten
- **Permissions as policy** — `chmod 444` enforces immutability at the OS level, no extra logic needed
- **Composable agents** — small focused prompts combine into powerful workflows
- **Human in the loop** — the model proposes, the human controls what runs

-----

## Directory Structure

```
~/lab/
├── README.md                  # master map, entry point for humans and agents
├── infra/                     # AI tooling, prompts, configs, convos
├── research/                  # deep dives into topics
├── experiments/               # low stakes, throw things at the wall
├── projects/                  # experiments that stuck
├── notes/                     # personal thoughts, runbooks, scratch pad
├── ideas/                     # brainstorm dumps, freeform
└── writing/                   # longform creative and blog content
    ├── blog/
    └── stories/
```

Each directory contains a `README.md` that describes what it is and what’s in it. This is the primary navigation mechanism for both humans and agents.

-----

## Pipeline

There is a natural flow between directories:

```
ideas/ → research/ → experiments/ → projects/
                                         ↓
                                    notes/ (runbooks, how-tos)
                                    writing/ (blog posts, stories)
```

Not every idea makes it all the way. That’s fine.

-----

## infra/

The control plane for all AI tooling.

```
infra/
├── README.md
├── convos/                    # canonical conversation store (UUID filenames)
├── prompts/
│   ├── system/                # agent identities and personas
│   ├── templates/             # reusable fill-in-the-blank prompts
│   └── workflows/             # multi-step orchestrated sequences
└── tools/
    └── chat/                  # the CLI chat tool
        ├── chat.py
        └── config.yaml
```

-----

## Prompt Library

All prompts live in `infra/prompts/`. Every prompt file uses YAML frontmatter.

### Frontmatter Schema

```yaml
---
title: Infrastructure Engineer
type: system              # system | template | workflow
model: claude-sonnet-4    # model this was tuned for
version: 1.2
timestamp: 2026-04-01T00:00:00Z
tags: [infra, ops]
status: active            # active | draft | archived
supersedes: null          # filename of previous version if applicable
---

Prompt body starts here...
```

**Rules:**

- Frontmatter must be at the very top of the file, no blank lines before opening `---`
- `status: archived` prompts are kept for reference but agents should not use them
- Bump `version` on meaningful changes
- Old versions go to `infra/prompts/_archive/`

### system/

Define who the agent is. Give it a point of view, not just a role.

```
infra/prompts/system/
├── lab-assistant.md          # general purpose, knows ~/lab layout
├── infra-engineer.md         # ops-focused, prefers boring technology
├── researcher.md             # deep dives, citation-aware
├── code-reviewer.md          # opinionated, pedantic on purpose
├── programmer.md             # writes and edits code, knows your conventions
├── brainstorming.md          # expansive, no evaluation, just generate
├── planning.md               # structures ideas into phases and milestones
├── documentation.md          # reads code, writes and updates docs
├── story-writer.md           # creative, maintains continuity across convos
├── blogger.md                # knows your voice, writes for your audience
└── curator.md                # audits the lab, suggests what to promote or archive
```

### templates/

Fill-in-the-blank prompts for recurring tasks. Use `{{VARIABLE}}` syntax.

```
infra/prompts/templates/
├── research-kickoff.md       # start a new research deep dive
├── experiment-plan.md        # before starting an experiment
├── tool-evaluation.md        # comparing two tools or approaches
├── incident-retro.md         # what went wrong and why
└── promote-to-project.md     # checklist when graduating an experiment
```

### workflows/

Multi-step orchestrated sequences. The agent executes steps in order, producing output at each stage.

```
infra/prompts/workflows/
├── new-experiment.md         # scaffold a new experiment end to end
├── research-to-experiment.md # convert research notes into an experiment plan
├── morning-briefing.md       # daily lab status summary
├── infra-audit.md            # review infra for drift or debt
└── lab-curate.md             # find orphaned work, suggest promotions
```

-----

## Conversation System

-----

## Context

### What

A **context** is the current working directory the chat CLI is operating within (a directory under `lab_root`). Context is a first-class concept: it determines what gets auto-injected, which human-readable convo symlinks are available, and which conversation the CLI resumes by default.

### When

- A context is selected at startup by restoring the last context from `~/.lab/chat_state.json` (if valid), otherwise it defaults to `lab_root`.
- A context changes when you run `/switch <path>`.

### Where

Context-related files live inside the context directory:

- `injected.yaml` — declarative per-topic injection configuration
- `convos/` — local symlinks to conversations in the canonical store
- `<context>/convos/context_state.json`
  - **Scope**: per-context
  - **Contains**: `last_convo`, `manual_inject`

### Why

Contexts keep AI work compartmentalized:

- A topic directory owns its own injection config (`injected.yaml`) and local convo symlinks.
- Switching context changes what the model sees (injections + “current context” metadata).
- Context-local state allows “resume where I left off” per topic without a large global registry.

### How

On `/switch <path>`, the CLI:

- Loads per-context state from `<context>/convos/context_state.json`.
- Selects the active conversation using priority:
  - `last_convo`, else `None`.
- Loads auto injections (`injected.yaml` and optional Makefile).
- Applies persisted manual injections (`manual_inject`).

If a conversation was active before the switch, the CLI appends a `*-meta.yaml` event into the conversation being left to record the jump (timestamp + destination context + destination convo). The destination conversation is not modified just because you navigated into it.

### Canonical Store

All conversations are stored in `infra/convos/` with UUID filenames:

```
infra/convos/
└── 550e8400-e29b-41d4-a716-446655440000/   # one directory per conversation
    ├── 0001-meta.yaml
    ├── 0002-user.yaml
    ├── 0003-asst.yaml
    ├── 0004-tool.yaml
    ├── 0005-asst.yaml
    ├── 0006-meta.yaml     # model switch, prompt change, etc.
    ├── 0007-user.yaml
    └── 0008-asst.yaml
```

### Local Symlinks

Within each topic directory, convos appear as human-readable named symlinks:

```
research/docker-networking/
├── README.md
├── injected.yaml
└── convos/
    └── docker-networking.yaml -> ~/lab/infra/convos/550e8400-e29b-41d4/
```

A single conversation can be symlinked into multiple topic directories if it spans topics.

### File Format

Each file in a convo directory is written once, immediately `chmod 444`, and never modified.

In addition to the initial `0001-meta.yaml`, the chat CLI appends additional numbered `*-meta.yaml` files whenever conversation-relevant state changes (context switch, model/endpoint, prompt set, injected file set). These meta snapshots make it possible to reconstruct “what the model saw” over time from the convo directory alone.

**Meta file** (`0001-meta.yaml`) — dict, always the first file:

```yaml
title: Docker Networking Deep Dive
uuid: 550e8400-e29b-41d4-a716-446655440000
timestamp: 2026-04-02T09:00:00Z
model: gpt-4o
endpoint: openai          # openai | local (ollama)
fork_of: null             # UUID of parent convo if forked
fork_at: null             # timestamp of message branched from
prompts:
  - prompt: infra-engineer
    version: 1.2
    snapshot: |
      You are an infrastructure engineer working in ~/lab/infra...
tags: [docker, networking]
status: active
```

**User file** (`0002-user.yaml`) — list with one item:

```yaml
- role: user
  content: Let's talk about docker networking
  timestamp: 2026-04-02T09:00:05Z
```

**Assistant file** (`0003-asst.yaml`):

```yaml
- role: asst
  content: Sure, let's start with the basics...
  timestamp: 2026-04-02T09:00:08Z
```

**Tool file** (`0004-tool.yaml`):

```yaml
- role: tool
  tool: read_file
  input:
    path: research/docker-networking/README.md
  output: |
    ... file contents ...
  timestamp: 2026-04-02T09:00:10Z
  status: success
```

**Subsequent meta file** (`0006-meta.yaml`) — records state changes mid-conversation:

```yaml
timestamp: 2026-04-02T09:15:00Z
model: llama3
endpoint: local
prompts:
  - prompt: infra-engineer
    version: 1.2
    snapshot: |
      ...
  - prompt: docker-specialist
    version: 1.0
    snapshot: |
      ...
```

**Parser rule:** walk files in sorted order. A dict file updates running state. A list file contains messages sent under the current state. No type field needed — structure is self-describing.

### Forking

To fork a conversation, start a new one with a backreference:

```yaml
# 0001-meta.yaml of the fork
title: Docker Networking — Volume Focus
uuid: 7c9e4f21-b83a-42c1-...
fork_of: 550e8400-e29b-41d4-...
fork_at: 2026-04-02T09:15:00Z
```

The tool replays the parent conversation up to `fork_at` before continuing. Forks are stored as independent UUID directories with their own symlinks.

### Prompts in Convos

Prompts are **referenced and snapshotted**. The `prompt` field in meta points to a filename in `infra/prompts/system/`. The `snapshot` field captures the exact body at the time the convo was created, stripped of frontmatter.

- **Resuming** a convo uses the snapshot — faithful replay
- **Starting fresh** uses the current prompt file
- **Forking** inherits the parent’s snapshots unless explicitly overridden

Multiple prompts compose in order. Each is snapshotted independently.

-----

## Injected Files

### Per-Topic Configuration

Each topic directory owns an `injected.yaml` that defines what files get loaded into context:

```yaml
# research/docker-networking/injected.yaml
- file: research/docker-networking/README.md
  auto: true              # loaded automatically on /switch
- file: infra/configs/docker.conf
  auto: false             # manually injected, prompted on /switch
```

`auto: true` files are silently loaded. `auto: false` files prompt for confirmation.

The chat CLI keeps an in-memory list of injected **file references**, and reads the current contents from disk whenever it builds the system prompt. This means injected content always reflects the latest state of the working tree.

The injection **selection** is refreshed on every conversation turn: before sending a message, the CLI rebuilds the injected file reference set from the current context's `injected.yaml` (and optional `Makefile`) plus `manual_inject` from `convos/context_state.json`.

If the effective injected set changes between turns, the CLI prints a brief notice and records an `injected_set_changed` event in the convo's `*-meta.yaml` stream with `added`, `removed`, and `injected_yaml_mtime`.

Manual injections made via `/inject <file>` persist per context in `<context>/convos/context_state.json` under the `manual_inject` list.

### Format in Prompt

Injected files are wrapped in XML tags:

```xml
<injected file="research/docker-networking/README.md" injected_at="2026-04-02T09:00:00Z">
... file contents ...
</injected>
```

### Makefile Auto-Injection

If a `Makefile` exists in the current context directory, it is auto-injected on `/switch` so the agent knows what targets are available without a separate tool call.

-----

## The Chat CLI

`infra/tools/chat/chat.py` — a Python readline CLI that talks to language models.

### Features

- OpenAI-compatible HTTP (works with OpenAI, Ollama, and vllm)
- Composable prompt system with snapshots
- Persistent conversations as immutable numbered files
- `/commands` for navigation and control
- Tab completion for commands and filenames
- Status line showing current state
- Persistent command line history in `~/.lab/.cli-history`
  - Appended per command (durable write), not only on exit
- Persistent last-used context in `~/.lab/chat_state.json`
  - **Scope**: global (across all contexts)
  - **Contains**: `last_context`, `first_convo`
- docopt-ng command line parsing using module `__doc__`

### Configuration

```yaml
# infra/config/chat.yaml
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
lab_root: /home/val/lab
conversation_store: infra/convos
prompt_library: infra/prompts
auto_inject_makefile: true
restore_last_convo: true
file_permissions:
  immutable: 444
  mutable: 644
  directory: 755
```

`lab_root` is authoritative from config. Global state in `~/.lab/chat_state.json` records the last `context`, but the CLI only restores a saved `context` if it still exists on disk and is inside the configured `lab_root`.

Per-context state lives in `<context>/convos/context_state.json`:

```json
{
  "last_convo": "<uuid>",
  "manual_inject": ["path/to/file", "path/to/other"]
}
```

### Commands

**Conversation:**

```
/convo [name|uuid]       change convo within current context
/convo list              list convos in current context
/convo new [name]        start new convo here
/convo fork [name]       fork current convo at last message
```

**Navigation:**

```
/switch [path]           change context directory (relative to ~/lab)
/switch list             list available contexts
```

**Prompts:**

```
/prompts                 list available prompts
/prompt add [name]       add a prompt to current convo
/prompt drop [name]      remove a prompt from current convo
```

**Injection:**

```
/inject [file]           inject a file into context
/inject list             show currently injected files
/inject drop [file]      remove a file from context
/inject clear            remove all injected files
```

**Model:**

```
/model [name]            switch model for current convo
/model list              list available models (local: ollama, remote: openai)
```

**Info:**

```
/show config             show current configuration
/show status             show current status
/show history            show conversation history
/status                  alias for /show status
/history                 alias for /show history
/help                    show command help
/quit                    exit the chat
```

You can also run shell commands by prefixing the line with `!`. This runs the command in the current context directory using a fresh shell process each time (not a TTY).

### Status Display

```
context: research/docker-networking
convo:   docker-networking (550e8400)
prompts: infra-engineer v1.2, docker-specialist v1.0
model:   llama3 (local)
messages: 14
```

### Model Backend

- **Ollama** for local models — pull and run, automatic memory management, model switching without restart, OpenAI-compatible endpoint at `localhost:11434`
- **VLLM** for high-performance local inference — OpenAI-compatible endpoint at `localhost:8000`
- **OpenAI** for cloud models — same HTTP interface, different endpoint and key

Ollama is preferred for multi-model experimentation. VLLM provides high-performance local inference. vLLM is not used — it requires a server restart to swap models.

## Implementation Details

### CLI Architecture

The CLI is implemented as a single Python file at `infra/tools/chat/chat.py` with:

- **docopt-ng** for command line parsing using the module's `__doc__` string
- **readline** for interactive input with tab completion and history
- **Persistent history** saved to `~/.lab/.cli-history`
- **OpenAI Python package** for API communication
- **PyYAML** for configuration and conversation file handling

### Dependencies

```toml
[project]
dependencies = [
    "docopt-ng>=0.7.2",
    "openai>=2.30.0",
    "pyaml>=26.2.1",
]
```

### Entry Point

The CLI is invoked via the Makefile:
```makefile
cli:
	PYTHONPATH=infra python3 -c "from infra.tools.chat.chat import main; main()"
```

Or directly with docopt-ng options:
```bash
python3 -c "from infra.tools.chat.chat import main; main()" --help
python3 -c "from infra.tools.chat.chat import main; main()" --version
```

-----

## MCP Server

A constrained filesystem MCP server exposing `~/lab` to agents. Read-only access is enforced by OS file permissions (`chmod 444`). The MCP server runs as the file owner and respects permissions naturally — no whitelist logic needed.

### Tools

```
read_file(path, start_line?, end_line?)
read_multiple_files(paths[])
write_file(path, content)
edit_file(path, old_str, new_str)
list_directory(path)
directory_tree(path)
search_files(path, pattern)
move_file(src, dst)
run_make(target)
tavily_search(query)
fetch_url(url)
git_status(path?)
git_diff(path?)
git_log(path?, limit?)
git_blame(path)
```

### Permission Model

|Permission|Meaning                                      |
|----------|---------------------------------------------|
|`444`     |Frozen — nobody writes, model reads freely   |
|`644`     |Active — MCP server can write, model can read|
|`755`     |Directory — traversable                      |

**Conventions:**

- Convo files are `chmod 444` immediately after writing — written once, locked forever
- Research notes in progress: `644`. Finalized: `444`
- Experiments in progress: `644`. Completed: `444`
- The lab’s mutability state is visible with `ls -la`

### Separation of Concerns

The MCP server is **only for the model** to explore and work in `~/lab`. It does not manage conversations. The Python chat tool handles all conversation persistence — writing numbered files, managing symlinks, locking files after write.

-----

## Agents

Each agent is a composition of prompts from `infra/prompts/`. Agents are not separate processes — they are identities loaded into the chat CLI via `/prompt add`.

### Core Agents

**Lab Assistant** (`system/lab-assistant.md`)
General purpose. Knows the full `~/lab` layout and conventions. Good default.

**Infra Engineer** (`system/infra-engineer.md`)
Ops-focused. Prefers boring, auditable solutions. Thinks in layers: networking → compute → storage → services. Always checks for existing scripts before writing new ones. Never hardcodes secrets.

**Researcher** (`system/researcher.md`)
Deep dive mode. Citation-aware. Reads broadly before concluding. Dumps structured findings into `research/topic/`. Uses Tavily and fetch_url heavily.

**Programmer** (`system/programmer.md`)
Writes and edits code. Knows your conventions from README. Uses `edit_file` for surgical changes. Runs tests via `run_make`. Never overwrites blindly.

**Code Reviewer** (`system/code-reviewer.md`)
Opinionated and pedantic on purpose. Finds problems you missed. Uses git_diff for context.

**Documentation Agent** (`system/documentation.md`)
Reads code, writes and updates docs. Keeps README files current. Knows frontmatter conventions. Good post-coding cleanup step.

### Creative Agents

**Brainstorming** (`system/brainstorming.md`)
Expansive, no constraints. Explicitly told not to evaluate — just generate. Dumps output to `ideas/`. Most freeform prompt in the library.

**Planning** (`system/planning.md`)
Takes a brainstorm or idea and structures it. Breaks into phases, milestones, tasks. Knows the lab layout so it can scaffold directories. Natural next step after brainstorming.

**Story Writer** (`system/story-writer.md`)
Creative, no technical constraints. Long-context aware — maintains continuity across convos. Uses fork heavily to explore alternate plot directions. Output goes to `writing/stories/`.

**Blogger** (`system/blogger.md`)
Takes research or notes and writes posts in your voice. Inject example posts to calibrate tone. Output goes to `writing/blog/`. Can have a publishing workflow in Makefile.

### Meta Agents

**Curator** (`system/curator.md`)
Periodic. Scans the whole lab. Finds orphaned experiments, stale research, forgotten ideas. Suggests what to promote, archive, or delete. Like a lab janitor.

**Synthesizer** (`system/synthesizer.md`)
Cross-cuts research, experiments, and convos. Connects dots across topics. “What have I learned about Docker across all my work?” Useful for periodic review sessions.

**Promotion Agent** (`workflows/promote-to-project.md`)
Specific workflow: experiment → project. Audits an experiment, writes a summary, creates project scaffold, moves files, updates READMEs.

-----

## Agent Pipelines

Natural flows between agents:

```
brainstorming → planning → new-experiment workflow → programmer → code-reviewer
                                                               ↓
researcher → research-to-experiment workflow                documentation
     ↓
  tavily_search + fetch_url
  → structured notes in research/topic/
```

And periodically:

```
curator → synthesizer → promotion agent
```

-----

## Git

`~/lab` is a single git repository. Everything is tracked.

**Conventions:**

- Commit straight to `main` — this is a personal lab
- Commit messages are descriptive but informal
- Convo files are committed as they are written — immutable history in git too
- `.gitignore` excludes secrets, `.env` files, and any `_local/` directories

-----

## Secrets

- Never committed to git
- Stored in `.env` files excluded by `.gitignore`
- Referenced by name in configs: `key_env: OPENAI_API_KEY`
- Model never sees secret values — only the tool resolves them at runtime

-----

## Conventions

- **README.md everywhere** — every directory has one
- **YAML frontmatter** — every prompt and note file starts with `---` frontmatter
- **Four-char role names** — `meta`, `user`, `asst`, `tool` — visual alignment in `ls`
- **Sequence padding** — `0001` through `9999` for convo file ordering
- **Relative paths** in symlinks and frontmatter — portability
- **Slugs for symlink names** — `docker-networking.yaml`, not `Docker Networking.yaml`
- **ISO 8601 timestamps** everywhere — `2026-04-02T09:00:00Z`
- **Lowercase filenames** — no spaces, hyphens as separators
