# Prompts

All AI prompts live here. Organized by type with YAML frontmatter.

## Structure

```
prompts/
├── system/          # agent identities and personas
├── templates/       # reusable fill-in-the-blank prompts  
└── workflows/       # multi-step orchestrated sequences
```

## Frontmatter Schema

Every prompt file uses YAML frontmatter:

```yaml
---
title: Infrastructure Engineer
type: system              # system | template | workflow
model: claude-sonnet-4    # model this was tuned for
version: 1.2
date: 2026-04-01
tags: [infra, ops]
status: active            # active | draft | archived
supersedes: null          # filename of previous version if applicable
---

Prompt body starts here...
```

## Rules

- Frontmatter must be at the very top, no blank lines before opening `---`
- `status: archived` prompts are kept for reference but not used
- Bump `version` on meaningful changes
- Old versions go to `infra/prompts/_archive/`

## Usage

Prompts are loaded into conversations via `/prompt add [name]`. Multiple prompts compose in order.
