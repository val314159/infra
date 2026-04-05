# Chat CLI

Python readline CLI that talks to language models.

## Features

- OpenAI-compatible HTTP (works with OpenAI and Ollama)
- Composable prompt system with snapshots
- Persistent conversations as immutable numbered files
- `/commands` for navigation and control
- Tab completion for commands and filenames
- Status line showing current state

## Files

- `chat.py` - main CLI implementation
- `config.yaml` - configuration and endpoints

## Usage

Run from lab root: `make` (which calls `PYTHONPATH=infra uv run -m chat-cli`)

The CLI handles all conversation persistence, prompt management, and navigation. It writes immutable conversation files to `../convos/` and manages symlinks in topic directories.
