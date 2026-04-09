#!/usr/bin/env python3
"""
Kelvin chat CLI.

Usage:
  chat.py [--config=<path>]
  chat.py init [--config=<path>]
  chat.py (-h | --help)
  chat.py --version
"""

from __future__ import annotations

import atexit
import json
import os
import re
import readline
import shlex
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from docopt import docopt
from openai import OpenAI

VERSION = "0.1.0"
DIR_MODE = 0o755
FILE_MODE = 0o644
FROZEN_MODE = 0o444
DEFAULT_CONFIG = {
    "default_model": "firmen102/qwen3.5-27b",
    "default_endpoint": "ollama",
    "endpoints": {
        "openai": {"url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY"},
        "ollama": {"url": "http://localhost:11434/v1", "key_env": None},
        "vllm": {"url": "http://localhost:8000/v1", "key_env": None},
    },
}
HELP = """Commands

Conversation:
  /convo
  /convo list
  /convo [name]
  /convo new [title]
  /convo fork [title]

Navigation:
  /switch [path]
  /switch list

Prompts:
  /prompt
  /prompt add [slug]
  /prompt drop [slug]

Injection:
  /inject [file]
  /inject list
  /inject drop [file]
  /inject clear

Model:
  /model
  /model [name]
  /model list

Info:
  /show config
  /show status
  /show history
  /status
  /history
  /help
  /quit

Shell:
  !<command>
"""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or (Path.home() / default)).expanduser()


def merge(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def slugify(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text or "conversation"


def short(text: str, n: int = 88) -> str:
    text = " ".join(text.strip().split())
    return text if len(text) <= n else text[: n - 1] + "..."


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing frontmatter")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            head = yaml.safe_load("".join(lines[1:i])) or {}
            body = "".join(lines[i + 1 :])
            return head, body
    raise ValueError("unterminated frontmatter")


def dump_frontmatter(head: dict[str, Any], body: str = "") -> str:
    meta = yaml.safe_dump(head, sort_keys=False).strip()
    return f"---\n{meta}\n---\n{body}"


@dataclass
class Record:
    owner: str
    name: str
    kind: str
    head: dict[str, Any]
    body: str


class Kelvin:
    def __init__(self, config_path: str | None):
        self.config_home = xdg("XDG_CONFIG_HOME", ".config") / "kelvin"
        self.data_home = xdg("XDG_DATA_HOME", ".local/share") / "kelvin"
        self.state_home = xdg("XDG_STATE_HOME", ".local/state") / "kelvin"
        self.cache_home = xdg("XDG_CACHE_HOME", ".cache") / "kelvin"
        self.config_file = Path(config_path).expanduser() if config_path else self.config_home / "config.yaml"
        self.last_context_file = self.state_home / "last_context"
        self.history_file = self.state_home / "history"
        self.convos_dir = self.data_home / "convos"
        self.prompts_dir = self.data_home / "prompts"
        self.clients: dict[str, OpenAI] = {}
        self.config = self.load_config()
        self.context = self.discover_context()
        self.kelvin_dir = self.context / ".kelvin"
        self.context_state_file = self.kelvin_dir / "state.json"
        self.local_injected_file = self.kelvin_dir / "local.injected"
        self.alias_dir = self.kelvin_dir / "convos"
        self.ensure_dir(self.config_home)
        self.ensure_dir(self.data_home)
        self.ensure_dir(self.state_home)
        self.ensure_dir(self.cache_home)
        self.ensure_dir(self.convos_dir)
        self.ensure_dir(self.prompts_dir)
        self.ensure_dir(self.alias_dir)
        self.touch(self.local_injected_file)
        self.touch(self.context_state_file, "{}\n")
        self.current_convo = self.load_context_state().get("last_convo")
        if self.current_convo and not self.convo_path(self.current_convo).is_dir():
            self.current_convo = None
            self.save_context_state()
        self.save_last_context()
        self.setup_history()

    def ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path, DIR_MODE)
        except OSError:
            pass

    def touch(self, path: Path, content: str = "") -> None:
        if path.exists():
            return
        self.ensure_dir(path.parent)
        path.write_text(content)
        try:
            os.chmod(path, FILE_MODE)
        except OSError:
            pass

    def read_yaml_file(self, path: Path, default: Any) -> Any:
        try:
            return yaml.safe_load(path.read_text()) or default
        except FileNotFoundError:
            return default
        except Exception:
            return default

    def write_json(self, path: Path, data: Any) -> None:
        self.ensure_dir(path.parent)
        path.write_text(json.dumps(data, indent=2) + "\n")
        try:
            os.chmod(path, FILE_MODE)
        except OSError:
            pass

    def load_config(self) -> dict[str, Any]:
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        loaded = self.read_yaml_file(self.config_file, {})
        if isinstance(loaded, dict):
            merge(cfg, loaded)
        return cfg

    def discover_context(self) -> Path:
        found = self.find_context(Path.cwd())
        if found:
            return found
        try:
            last = Path(self.last_context_file.read_text().strip()).expanduser()
            if last and (last / ".kelvin").is_dir():
                return last.resolve()
        except Exception:
            pass
        raise SystemExit("No Kelvin context found. Run `chat.py init` in a project directory.")

    def find_context(self, start: Path) -> Path | None:
        start = start.resolve()
        if start.is_file():
            start = start.parent
        for path in [start, *start.parents]:
            if (path / ".kelvin").is_dir():
                return path
        return None

    def save_last_context(self) -> None:
        self.ensure_dir(self.last_context_file.parent)
        self.last_context_file.write_text(str(self.context.resolve()) + "\n")
        try:
            os.chmod(self.last_context_file, FILE_MODE)
        except OSError:
            pass

    def load_context_state(self) -> dict[str, Any]:
        state = self.read_yaml_file(self.context_state_file, {})
        return state if isinstance(state, dict) else {}

    def save_context_state(self) -> None:
        self.write_json(self.context_state_file, {"last_convo": self.current_convo})

    def setup_history(self) -> None:
        self.ensure_dir(self.history_file.parent)
        try:
            readline.read_history_file(self.history_file)
        except FileNotFoundError:
            pass
        except Exception:
            pass

        def write_history() -> None:
            try:
                readline.write_history_file(self.history_file)
                os.chmod(self.history_file, FILE_MODE)
            except Exception:
                pass

        readline.parse_and_bind("tab: complete")
        atexit.register(write_history)

    def convo_path(self, convo_id: str) -> Path:
        return self.convos_dir / convo_id

    def convo_root_meta(self, convo_id: str) -> dict[str, Any]:
        path = self.convo_path(convo_id) / "0001-meta"
        try:
            head, _ = parse_frontmatter(path.read_text())
            return head
        except Exception:
            return {}

    def alias_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if not self.alias_dir.exists():
            return out
        for path in sorted(self.alias_dir.iterdir()):
            if not path.is_symlink():
                continue
            try:
                target = path.resolve()
            except OSError:
                continue
            if target.parent == self.convos_dir:
                out[path.name] = target.name
        return out

    def alias_for(self, convo_id: str) -> str | None:
        aliases = [name for name, cid in self.alias_map().items() if cid == convo_id]
        if not aliases:
            return None
        root = self.convo_root_meta(convo_id).get("name")
        return root if root in aliases else sorted(aliases)[0]

    def unique_slug(self, base: str, *, refuse: bool) -> str:
        slug = slugify(base)
        if refuse and (self.alias_dir / slug).exists():
            raise ValueError(f"alias already exists: {slug}")
        if refuse or not (self.alias_dir / slug).exists():
            return slug
        n = 2
        while (self.alias_dir / f"{slug}-{n}").exists():
            n += 1
        return f"{slug}-{n}"

    def new_record_name(self, convo_id: str, kind: str) -> str:
        nums = []
        for path in self.convo_path(convo_id).glob("*-*"):
            try:
                nums.append(int(path.name.split("-", 1)[0]))
            except ValueError:
                pass
        return f"{(max(nums) + 1 if nums else 1):04d}-{kind}"

    def write_record(self, convo_id: str, kind: str, head: dict[str, Any], body: str = "") -> Path:
        convo_dir = self.convo_path(convo_id)
        self.ensure_dir(convo_dir)
        path = convo_dir / self.new_record_name(convo_id, kind)
        path.write_text(dump_frontmatter(head, body))
        os.chmod(path, FROZEN_MODE)
        return path

    def write_meta(self, convo_id: str, **head: Any) -> None:
        self.write_record(convo_id, "meta", {"timestamp": now(), **head})

    def create_alias(self, convo_id: str, slug: str) -> None:
        alias = self.alias_dir / slug
        if alias.exists() or alias.is_symlink():
            raise ValueError(f"alias already exists: {slug}")
        alias.symlink_to(self.convo_path(convo_id))

    def read_dir_records(self, convo_id: str) -> list[Record]:
        out = []
        if not self.convo_path(convo_id).is_dir():
            return out
        for path in sorted(self.convo_path(convo_id).iterdir(), key=lambda p: p.name):
            if not path.is_file():
                continue
            try:
                head, body = parse_frontmatter(path.read_text())
                kind = path.name.split("-", 1)[1]
            except Exception:
                continue
            out.append(Record(convo_id, path.name, kind, head, body))
        return out

    def replay_records(self, convo_id: str) -> list[Record]:
        own = self.read_dir_records(convo_id)
        if not own:
            return []
        root = own[0].head
        parent_id = root.get("fork_of")
        if not parent_id:
            return own
        parent = self.replay_records(parent_id)
        if root.get("fork_file"):
            cut = []
            for rec in parent:
                cut.append(rec)
                if rec.owner == parent_id and rec.name == root["fork_file"]:
                    break
            parent = cut
        elif root.get("fork_at"):
            parent = [rec for rec in parent if (rec.head.get("timestamp") or "") <= root["fork_at"]]
        return parent + own

    def prompt_path(self, slug: str) -> Path:
        hits = []
        for group in ("system", "templates", "workflows"):
            hits.extend(sorted((self.prompts_dir / group).glob(f"{slug}.md")))
        if not hits:
            raise FileNotFoundError(slug)
        if len(hits) > 1:
            raise ValueError(f"duplicate prompt slug: {slug}")
        return hits[0]

    def prompt_body(self, slug: str) -> str:
        head, body = parse_frontmatter(self.prompt_path(slug).read_text())
        title = head.get("title") or slug
        return f"# {title}\n\n{body.strip()}".strip()

    def prompt_slugs(self) -> list[str]:
        seen: dict[str, Path] = {}
        dupes: set[str] = set()
        for group in ("system", "templates", "workflows"):
            for path in sorted((self.prompts_dir / group).glob("*.md")):
                slug = path.stem
                if slug in seen:
                    dupes.add(slug)
                else:
                    seen[slug] = path
        return [slug for slug in sorted(seen) if slug not in dupes]

    def normalize_selected_path(self, raw: str) -> str:
        path = Path(raw).expanduser()
        if path.is_absolute():
            return str(path.resolve(strict=False))
        full = (self.context / path).resolve(strict=False)
        try:
            return str(full.relative_to(self.context.resolve()))
        except ValueError:
            return str(full)

    def selected_path(self, text: str) -> Path:
        path = Path(text)
        return path if path.is_absolute() else self.context / path

    def injected_entries(self) -> list[tuple[bool, str]]:
        out = []
        for file in (self.context / ".injected", self.local_injected_file):
            try:
                lines = file.read_text().splitlines()
            except FileNotFoundError:
                continue
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                negate = line.startswith("-")
                raw = line[1:] if negate else line
                out.append((not negate, self.normalize_selected_path(raw)))
        return out

    def effective_injected(self, warn: bool = False) -> list[str]:
        state: dict[str, bool] = {}
        for include, path in self.injected_entries():
            state.pop(path, None)
            state[path] = include
        out = []
        for path, include in state.items():
            if not include:
                continue
            full = self.selected_path(path)
            if full.exists():
                out.append(path)
            elif warn:
                print(f"warning: missing injected file: {path}")
        return out

    def append_local_injected(self, line: str) -> None:
        self.ensure_dir(self.local_injected_file.parent)
        with self.local_injected_file.open("a") as f:
            f.write(line + "\n")
        os.chmod(self.local_injected_file, FILE_MODE)

    def rewrite_local_injected(self, lines: list[str]) -> None:
        self.local_injected_file.write_text("".join(f"{line}\n" for line in lines))
        os.chmod(self.local_injected_file, FILE_MODE)

    def current_state(self) -> dict[str, Any]:
        state = {
            "title": None,
            "name": None,
            "model": self.config["default_model"],
            "endpoint": self.config["default_endpoint"],
            "prompts": [],
            "injected": [],
        }
        for rec in self.replay_records(self.current_convo) if self.current_convo else []:
            if rec.kind != "meta":
                continue
            head = rec.head
            if "uuid" in head:
                state["title"] = head.get("title")
                state["name"] = head.get("name")
                state["model"] = head.get("model", state["model"])
                state["endpoint"] = head.get("endpoint", state["endpoint"])
                state["prompts"] = [p["prompt"] for p in head.get("prompts", []) if isinstance(p, dict) and p.get("prompt")]
                continue
            match head.get("event"):
                case "model_changed":
                    state["model"] = head.get("model", state["model"])
                    state["endpoint"] = head.get("endpoint", state["endpoint"])
                case "prompt_added":
                    prompt = head.get("prompt")
                    if prompt and prompt not in state["prompts"]:
                        state["prompts"].append(prompt)
                case "prompt_dropped":
                    prompt = head.get("prompt")
                    state["prompts"] = [p for p in state["prompts"] if p != prompt]
                case "injected_set_changed":
                    state["injected"] = list(head.get("injected") or [])
        return state

    def render_context_blob(self, prompts: list[str], injected: list[str]) -> str:
        parts = []
        for slug in prompts:
            try:
                parts.append(self.prompt_body(slug))
            except Exception:
                parts.append(f"[missing prompt: {slug}]")
        for item in injected:
            path = self.selected_path(item)
            try:
                body = path.read_text()
                mode = f"{path.stat().st_mode & 0o777:03o}"
                parts.append(f'<injected file="{item}" mode="{mode}">\n{body}\n</injected>')
            except Exception:
                parts.append(f'[missing injected file: {item}]')
        return "\n\n".join(part for part in parts if part).strip()

    def render_tool_note(self, rec: Record) -> str:
        cmd = rec.head.get("cmd", "")
        return f"<tool name=\"{rec.head.get('tool', 'shell')}\" cmd=\"{cmd}\">\n{rec.body}\n</tool>"

    def render_meta_note(self, rec: Record) -> str | None:
        match rec.head.get("event"):
            case "shell_bang":
                return (
                    f"<shell cmd=\"{rec.head.get('cmd', '')}\" cwd=\"{rec.head.get('cwd', '')}\" "
                    f"exit_code=\"{rec.head.get('exit_code', '')}\" />"
                )
            case "switched_away":
                return (
                    f"<switch to_context=\"{rec.head.get('to_context', '')}\" "
                    f"to_convo=\"{rec.head.get('to_convo', '')}\" />"
                )
        return None

    def replay_messages(self) -> tuple[dict[str, Any], list[dict[str, Any]], list[Record]]:
        state = {
            "title": None,
            "name": None,
            "model": self.config["default_model"],
            "endpoint": self.config["default_endpoint"],
            "prompts": [],
            "injected": [],
        }
        messages: list[dict[str, Any]] = []
        records = self.replay_records(self.current_convo) if self.current_convo else []
        last_blob = None
        for rec in records:
            if rec.kind == "meta":
                head = rec.head
                if "uuid" in head:
                    state["title"] = head.get("title")
                    state["name"] = head.get("name")
                    state["model"] = head.get("model", state["model"])
                    state["endpoint"] = head.get("endpoint", state["endpoint"])
                    state["prompts"] = [p["prompt"] for p in head.get("prompts", []) if isinstance(p, dict) and p.get("prompt")]
                    blob = self.render_context_blob(state["prompts"], state["injected"])
                    if blob and blob != last_blob:
                        messages.append({"role": "system", "content": blob})
                        last_blob = blob
                    continue
                match head.get("event"):
                    case "model_changed":
                        state["model"] = head.get("model", state["model"])
                        state["endpoint"] = head.get("endpoint", state["endpoint"])
                    case "prompt_added":
                        prompt = head.get("prompt")
                        if prompt and prompt not in state["prompts"]:
                            state["prompts"].append(prompt)
                    case "prompt_dropped":
                        prompt = head.get("prompt")
                        state["prompts"] = [p for p in state["prompts"] if p != prompt]
                    case "injected_set_changed":
                        state["injected"] = list(head.get("injected") or [])
                    case _:
                        note = self.render_meta_note(rec)
                        if note:
                            messages.append({"role": "system", "content": note})
                blob = self.render_context_blob(state["prompts"], state["injected"])
                if blob and blob != last_blob:
                    messages.append({"role": "system", "content": blob})
                    last_blob = blob
            elif rec.kind == "user":
                messages.append({"role": "user", "content": rec.body})
            elif rec.kind == "asst":
                messages.append({"role": "assistant", "content": rec.body})
            elif rec.kind == "tool":
                messages.append({"role": "system", "content": self.render_tool_note(rec)})
        return state, messages, records

    def endpoint_client(self, endpoint: str) -> OpenAI:
        if endpoint in self.clients:
            return self.clients[endpoint]
        cfg = self.config["endpoints"].get(endpoint)
        if not cfg:
            raise ValueError(f"unknown endpoint: {endpoint}")
        key_env = cfg.get("key_env")
        key = os.environ.get(key_env, "x") if key_env else "x"
        self.clients[endpoint] = OpenAI(base_url=cfg["url"], api_key=key)
        return self.clients[endpoint]

    def ensure_convo(self) -> bool:
        if self.current_convo:
            return True
        print("no active conversation; use /convo new")
        return False

    def maybe_log_injected_change(self) -> None:
        if not self.ensure_convo():
            return
        state = self.current_state()
        current = self.effective_injected(warn=True)
        previous = list(state["injected"])
        if current == previous:
            return
        self.write_meta(
            self.current_convo,
            event="injected_set_changed",
            reason="pre_send",
            injected=current,
            added=[p for p in current if p not in previous],
            removed=[p for p in previous if p not in current],
        )

    def write_switch_event(self, old_convo: str | None, to_context: Path, to_convo: str | None) -> None:
        if not old_convo:
            return
        self.write_meta(old_convo, event="switched_away", to_context=str(to_context), to_convo=to_convo)

    def resolve_convo(self, name: str) -> str | None:
        aliases = self.alias_map()
        if name in aliases:
            return aliases[name]
        path = self.convo_path(name)
        if path.is_dir():
            return name
        return None

    def set_current_convo(self, convo_id: str | None) -> None:
        self.current_convo = convo_id
        self.save_context_state()

    def create_convo(self, title: str | None, *, fork: bool) -> None:
        base_state = self.current_state() if self.current_convo else {
            "model": self.config["default_model"],
            "endpoint": self.config["default_endpoint"],
            "prompts": [],
            "title": None,
            "name": None,
        }
        convo_id = str(uuid.uuid4())
        if title:
            slug = self.unique_slug(title, refuse=not fork)
            convo_title = title
        elif fork:
            parent_alias = self.alias_for(self.current_convo) or base_state.get("name") or "conversation"
            i = 1
            while (self.alias_dir / f"{parent_alias}-fork-{i}").exists():
                i += 1
            slug = f"{parent_alias}-fork-{i}"
            convo_title = f'{base_state.get("title") or "Conversation"} Fork {i}'
        else:
            convo_title = "Untitled Conversation"
            slug = self.unique_slug(convo_title, refuse=False)
        head = {
            "title": convo_title,
            "name": slug,
            "uuid": convo_id,
            "timestamp": now(),
            "context": str(self.context),
            "model": base_state["model"],
            "endpoint": base_state["endpoint"],
            "fork_of": None,
            "fork_at": None,
            "fork_file": None,
            "prompts": [{"prompt": slug} for slug in base_state["prompts"]],
        }
        if fork:
            if not self.ensure_convo():
                return
            _, _, records = self.replay_messages()
            cut = records[-1] if records else None
            head["fork_of"] = self.current_convo
            head["fork_at"] = cut.head.get("timestamp") if cut else now()
            head["fork_file"] = cut.name if cut else None
        try:
            self.write_record(convo_id, "meta", head)
            self.create_alias(convo_id, slug)
        except Exception as e:
            print(e)
            return
        self.write_switch_event(self.current_convo, self.context, convo_id)
        self.set_current_convo(convo_id)
        print(f"{slug} -> {convo_id}")

    def switch_convo(self, name: str) -> None:
        convo_id = self.resolve_convo(name)
        if not convo_id:
            print(f"unknown conversation: {name}")
            return
        if convo_id == self.current_convo:
            return
        old = self.current_convo
        self.write_switch_event(old, self.context, convo_id)
        self.set_current_convo(convo_id)
        meta = self.convo_root_meta(convo_id)
        print(f"{meta.get('name', convo_id)} -> {convo_id}")

    def list_convos(self) -> None:
        aliases = self.alias_map()
        seen = set()
        for alias, convo_id in sorted(aliases.items()):
            meta = self.convo_root_meta(convo_id)
            marker = "*" if convo_id == self.current_convo else " "
            print(f"{marker} {alias}  {meta.get('title', '')}  {convo_id}")
            seen.add(convo_id)
        if self.current_convo and self.current_convo not in seen:
            meta = self.convo_root_meta(self.current_convo)
            marker = "*"
            print(f"{marker} {meta.get('name', self.current_convo)}  {meta.get('title', '')}  {self.current_convo}")

    def switch_context(self, raw: str) -> None:
        target = Path(raw).expanduser()
        if not target.is_absolute():
            target = (Path.cwd() / target).resolve()
        found = self.find_context(target)
        if not found:
            print(f"no Kelvin context under: {raw}")
            return
        to_convo = self.read_yaml_file(found / ".kelvin" / "state.json", {}).get("last_convo")
        old = self.current_convo
        self.write_switch_event(old, found, to_convo)
        self.context = found
        self.kelvin_dir = self.context / ".kelvin"
        self.context_state_file = self.kelvin_dir / "state.json"
        self.local_injected_file = self.kelvin_dir / "local.injected"
        self.alias_dir = self.kelvin_dir / "convos"
        self.ensure_dir(self.alias_dir)
        self.touch(self.local_injected_file)
        self.touch(self.context_state_file, "{}\n")
        self.current_convo = self.load_context_state().get("last_convo")
        if self.current_convo and not self.convo_path(self.current_convo).is_dir():
            self.current_convo = None
            self.save_context_state()
        self.save_last_context()
        print(self.context)

    def list_contexts(self) -> None:
        seen = set()
        for base in {Path.cwd().resolve(), self.context}:
            for path in base.rglob(".kelvin"):
                ctx = path.parent
                if ctx not in seen:
                    seen.add(ctx)
                    marker = "*" if ctx == self.context else " "
                    print(f"{marker} {ctx}")

    def show_prompts(self) -> None:
        active = self.current_state()["prompts"] if self.current_convo else []
        print("active:", ", ".join(active) if active else "-")
        all_prompts = self.prompt_slugs()
        print("available:", ", ".join(all_prompts) if all_prompts else "-")

    def prompt_add(self, slug: str) -> None:
        if not self.ensure_convo():
            return
        try:
            self.prompt_path(slug)
        except Exception as e:
            print(e)
            return
        state = self.current_state()
        if slug in state["prompts"]:
            return
        self.write_meta(self.current_convo, event="prompt_added", prompt=slug)

    def prompt_drop(self, slug: str) -> None:
        if not self.ensure_convo():
            return
        if slug not in self.current_state()["prompts"]:
            return
        self.write_meta(self.current_convo, event="prompt_dropped", prompt=slug)

    def show_model(self) -> None:
        state = self.current_state() if self.current_convo else {
            "model": self.config["default_model"],
            "endpoint": self.config["default_endpoint"],
        }
        print(f"{state['model']} @ {state['endpoint']}")

    def set_model(self, raw: str) -> None:
        if not self.ensure_convo():
            return
        endpoint = self.current_state()["endpoint"]
        model = raw
        if ":" in raw:
            maybe_endpoint, maybe_model = raw.split(":", 1)
            if maybe_endpoint in self.config["endpoints"]:
                endpoint, model = maybe_endpoint, maybe_model
        self.write_meta(self.current_convo, event="model_changed", model=model, endpoint=endpoint)

    def list_models(self) -> None:
        current = self.current_state() if self.current_convo else {
            "model": self.config["default_model"],
            "endpoint": self.config["default_endpoint"],
        }
        print(f"current: {current['model']} @ {current['endpoint']}")
        for name, cfg in self.config["endpoints"].items():
            print(f"{name}: {cfg['url']}")

    def inject_add(self, raw: str) -> None:
        path = self.normalize_selected_path(raw)
        line = f"./{path}" if path.startswith("-") else path
        self.append_local_injected(line)

    def inject_drop(self, raw: str) -> None:
        path = self.normalize_selected_path(raw)
        line = f"./{path}" if path.startswith("-") else path
        self.append_local_injected(f"-{line}")

    def inject_clear(self) -> None:
        lines = []
        for path in self.effective_injected():
            line = f"./{path}" if path.startswith("-") else path
            lines.append(f"-{line}")
        self.rewrite_local_injected(lines)

    def inject_list(self) -> None:
        for path in self.effective_injected():
            print(path)
        if not self.effective_injected():
            print("-")

    def show_status(self) -> None:
        state = self.current_state() if self.current_convo else {
            "title": None,
            "name": None,
            "model": self.config["default_model"],
            "endpoint": self.config["default_endpoint"],
            "prompts": [],
        }
        print(f"context: {self.context}")
        print(f"convo: {self.current_convo or '-'}")
        if self.current_convo:
            print(f"title: {state['title'] or '-'}")
            print(f"name: {state['name'] or self.alias_for(self.current_convo) or '-'}")
        print(f"model: {state['model']} @ {state['endpoint']}")
        print(f"prompts: {', '.join(state['prompts']) or '-'}")
        print(f"injected: {', '.join(self.effective_injected()) or '-'}")

    def show_config(self) -> None:
        print(f"config: {self.config_file}")
        print(yaml.safe_dump(self.config, sort_keys=False).strip())

    def show_history(self) -> None:
        if not self.ensure_convo():
            return
        for rec in self.replay_records(self.current_convo):
            if rec.kind == "meta" and "uuid" in rec.head:
                print(f"{rec.name} meta {rec.head.get('title', '')} {rec.head.get('uuid', '')}")
            elif rec.kind == "meta":
                event = rec.head.get("event", "meta")
                print(f"{rec.name} meta {event}")
            elif rec.kind == "tool":
                print(f"{rec.name} tool {rec.head.get('tool', 'shell')} {short(rec.head.get('cmd', ''))}")
            else:
                print(f"{rec.name} {rec.head.get('role', rec.kind)} {short(rec.body)}")

    def bang(self, cmd: str) -> None:
        if not cmd.strip():
            return
        proc = subprocess.run(["bash", "-c", cmd], cwd=self.context)
        if self.current_convo:
            self.write_meta(
                self.current_convo,
                event="shell_bang",
                cmd=cmd,
                cwd=str(self.context),
                exit_code=proc.returncode,
            )

    def tool_result(self, cmd: str) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                ["bash", "-c", cmd],
                cwd=self.context,
                capture_output=True,
                text=True,
            )
            return {
                "success": True,
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def chat(self, text: str) -> None:
        if not self.ensure_convo():
            return
        self.maybe_log_injected_change()
        state, messages, _ = self.replay_messages()
        self.write_record(self.current_convo, "user", {"role": "user", "timestamp": now()}, text)
        messages.append({"role": "user", "content": text})
        try:
            client = self.endpoint_client(state["endpoint"])
            pending: list[str] = []
            while True:
                resp = client.chat.completions.create(
                    model=state["model"],
                    messages=messages,
                    tools=[
                        {
                            "type": "function",
                            "function": {
                                "name": "shell",
                                "description": "Run a shell command in the active context directory.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"cmd": {"type": "string"}},
                                    "required": ["cmd"],
                                    "additionalProperties": False,
                                },
                            },
                        }
                    ],
                )
                msg = resp.choices[0].message
                if msg.content:
                    pending.append(msg.content)
                calls = list(msg.tool_calls or [])
                if not calls:
                    body = "\n\n".join(part.strip() for part in pending if part.strip()).strip()
                    self.write_record(
                        self.current_convo,
                        "asst",
                        {"role": "assistant", "timestamp": now()},
                        body,
                    )
                    if body:
                        print(body)
                    return
                messages.append(msg.model_dump(exclude_none=True))
                for call in calls:
                    try:
                        args = json.loads(call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    cmd = str(args.get("cmd", "")).strip()
                    result = self.tool_result(cmd)
                    body = json.dumps(result, separators=(",", ":"))
                    self.write_record(
                        self.current_convo,
                        "tool",
                        {"role": "tool", "timestamp": now(), "tool": "shell", "cmd": cmd},
                        body,
                    )
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": body})
        except Exception as e:
            print(f"chat error: {e}")

    def handle(self, line: str) -> bool:
        if line.startswith("!"):
            self.bang(line[1:])
            return True
        if not line.startswith("/"):
            return False
        try:
            parts = shlex.split(line)
        except ValueError as e:
            print(e)
            return True
        if not parts:
            return True
        cmd = parts[0][1:]
        args = parts[1:]
        if cmd in {"quit", "exit"}:
            raise EOFError
        if cmd == "help":
            print(HELP)
        elif cmd == "convo":
            if not args or args[0] == "list":
                self.list_convos()
            elif args[0] == "new":
                self.create_convo(" ".join(args[1:]).strip() or None, fork=False)
            elif args[0] == "fork":
                self.create_convo(" ".join(args[1:]).strip() or None, fork=True)
            else:
                self.switch_convo(" ".join(args).strip())
        elif cmd == "switch":
            if not args:
                print(self.context)
            elif args[0] == "list":
                self.list_contexts()
            else:
                self.switch_context(" ".join(args).strip())
        elif cmd == "prompt":
            if not args:
                self.show_prompts()
            elif args[0] == "add" and len(args) > 1:
                self.prompt_add(" ".join(args[1:]).strip())
            elif args[0] == "drop" and len(args) > 1:
                self.prompt_drop(" ".join(args[1:]).strip())
            else:
                print("usage: /prompt [add|drop] [slug]")
        elif cmd == "inject":
            if not args or args[0] == "list":
                self.inject_list()
            elif args[0] == "drop" and len(args) > 1:
                self.inject_drop(" ".join(args[1:]).strip())
            elif args[0] == "clear":
                self.inject_clear()
            else:
                self.inject_add(" ".join(args).strip())
        elif cmd == "model":
            if not args:
                self.show_model()
            elif args[0] == "list":
                self.list_models()
            else:
                self.set_model(" ".join(args).strip())
        elif cmd in {"status"}:
            self.show_status()
        elif cmd in {"history"}:
            self.show_history()
        elif cmd == "show":
            if not args or args[0] == "status":
                self.show_status()
            elif args[0] == "config":
                self.show_config()
            elif args[0] == "history":
                self.show_history()
            else:
                print("usage: /show [config|status|history]")
        else:
            print(f"unknown command: /{cmd}")
        return True

    def prompt(self) -> str:
        name = self.alias_for(self.current_convo) if self.current_convo else "-"
        state = self.current_state() if self.current_convo else {
            "model": self.config["default_model"],
            "endpoint": self.config["default_endpoint"],
        }
        return f"{self.context.name}:{name}:{state['endpoint']} > "

    def loop(self) -> None:
        while True:
            try:
                line = input(self.prompt())
            except EOFError:
                print()
                return
            except KeyboardInterrupt:
                print()
                continue
            if not line.strip():
                continue
            try:
                if not self.handle(line):
                    self.chat(line)
            except EOFError:
                print()
                return


def init_context() -> None:
    root = Path.cwd().resolve()
    kelvin = root / ".kelvin"
    kelvin.mkdir(exist_ok=True)
    os.chmod(kelvin, DIR_MODE)
    (kelvin / "convos").mkdir(exist_ok=True)
    os.chmod(kelvin / "convos", DIR_MODE)
    (kelvin / "state.json").write_text('{\n  "last_convo": null\n}\n')
    os.chmod(kelvin / "state.json", FILE_MODE)
    (kelvin / "local.injected").write_text("")
    os.chmod(kelvin / "local.injected", FILE_MODE)
    print(f"initialized {kelvin}")
    print("recommend adding `.kelvin/` to .gitignore")


def main(argv: list[str] | None = None) -> None:
    args = docopt(__doc__, argv=argv, version=VERSION)
    if args["init"]:
        init_context()
        return
    Kelvin(args["--config"]).loop()


if __name__ == "__main__":
    main()
