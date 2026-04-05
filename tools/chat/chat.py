#!/usr/bin/env python3
"""
Lab Infra Chat CLI

A readline-based chat interface for AI conversations with persistent storage,
prompt composition, and filesystem navigation.

Usage:
  chat.py [--config=<path>] [--help] [--version]

Options:
  --config=<path>    Path to configuration file [default: infra/config/chat.yaml]
  --help             Show this help message
  --version          Show version

Description:
  The Lab Infra Chat CLI provides an interactive interface for AI conversations
  with persistent storage, composable prompts, and filesystem navigation.
  
  Features:
  - OpenAI-compatible HTTP (works with OpenAI, Ollama, and vllm)
  - Composable prompt system with snapshots
  - Persistent conversations as immutable numbered files
  - Slash commands for navigation and control
  - Tab completion for commands and filenames
  - Status line showing current state
"""

__version__ = '0.1.0'

HELP_MESSAGE = '''Lab Infra Chat CLI Commands

Conversation:
  /convo [name|uuid]       Change or list conversations
  /convo new [name]        Start new conversation
  /convo list              List conversations in current context

Navigation:
  /switch [path]           Change context directory
  /switch list             List available contexts

Prompts:
  /prompts                 List available prompts
  /prompt add [name]       Add prompt to current conversation
  /prompt drop [name]      Remove prompt from current conversation

Injection:
  /inject [file]           Inject file into context
  /inject list             Show currently injected files
  /inject drop [file]      Remove injected file
  /inject clear            Remove all injected files

Model:
  /model [name]            Switch model (optionally with endpoint)
  /model list              List available endpoints

Info:
  /show config            Show current configuration
  /show status            Show current status
  /show history           Show conversation history
  /status                 Alias for /show status
  /history                Alias for /show history
  /help                   Show this help
  /quit                   Exit the chat
  /exit                   Alias for /quit

Examples:
  /switch research/docker
  /prompt add researcher
  /inject README.md
  /model gpt-4o:local
'''

import os
import sys
import uuid
import yaml as pyyaml
import json
import readline
import glob
import subprocess
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import openai
from docopt import docopt

class ChatCLI:
    # Unix permission constants (core architectural choices)
    PERM_IMMUTABLE = 0o444  # read-only for all
    PERM_MUTABLE = 0o644    # read-write for owner, read-only for others
    PERM_DIRECTORY = 0o755  # read/write/execute for owner, read/execute for others

    @property
    def lab_home(self) -> Path:
        return Path.home() / '.lab'

    def get_context_convos_dir(self, context: Optional[Path] = None) -> Path:
        ctx = context or self.current_context
        return ctx / 'convos'

    def get_context_state_file(self, context: Optional[Path] = None) -> Path:
        return self.get_context_convos_dir(context) / 'context_state.json'

    def __init__(self, config_path: str = None):
        self.config = self.load_config(config_path)

        self.lab_root = Path(self.config['lab_root'])
        self.convos_dir = Path(self.config['conversation_store'])
        self.prompts_dir = Path(self.config['prompt_library'])
        self.state_file = self.lab_home / 'chat_state.json'
        self.first_convo: Optional[str] = None
        
        # Current state
        self.current_context = self.lab_root
        self.current_convo = None
        self.current_prompts = []
        self.current_model = self.config['default_model']
        self.current_endpoint = self.config['default_endpoint']
        self.injected_files = []

        self.restore_last_convo = bool(self.config.get('restore_last_convo', True))
        self.last_injected_set: Optional[set] = None

        self.load_state()
        self.load_context_state()
        self.inject_files()
        self.apply_manual_injections_from_context_state()
        self.last_injected_set = {inj.get('file') for inj in self.injected_files if isinstance(inj, dict)}
        
        # Setup OpenAI client
        self.setup_openai()
        
        # Ensure directories exist
        self.convos_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup history and readline
        self.setup_history()
        self.setup_completion()

    def is_valid_context(self, context_path: Path) -> bool:
        try:
            context_resolved = context_path.resolve()
            lab_root_resolved = self.lab_root.resolve()
        except Exception:
            return False

        if context_resolved == lab_root_resolved:
            return True

        return lab_root_resolved in context_resolved.parents

    def load_state(self):
        if not self.state_file.exists():
            return

        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
        except Exception:
            return

        ctx = state.get('last_context')

        if isinstance(ctx, str):
            candidate = Path(ctx)
            if not candidate.is_absolute():
                candidate = self.lab_root / candidate

            if candidate.exists() and candidate.is_dir() and self.is_valid_context(candidate):
                self.current_context = candidate

        fc = state.get('first_convo')
        if isinstance(fc, str) and fc:
            self.first_convo = fc

    def save_state(self):
        try:
            self.lab_home.mkdir(parents=True, exist_ok=True)
            state = {
                'lab_root': str(self.lab_root.resolve()),
                'last_context': str(self.current_context.resolve()),
                'first_convo': self.first_convo,
                'saved_at': datetime.datetime.now().isoformat() + 'Z',
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2, sort_keys=True)
        except Exception:
            return

    def load_context_state(self):
        context_state_file = self.get_context_state_file()
        if not context_state_file.exists():
            self.current_context_state = {}
            self.current_convo = None
            return

        try:
            with open(context_state_file, 'r') as f:
                state = json.load(f)
        except Exception:
            self.current_context_state = {}
            self.current_convo = None
            return

        if not isinstance(state, dict):
            state = {}

        self.current_context_state = state

        if not self.restore_last_convo:
            self.current_convo = None
            return

        candidates = [
            state.get('last_convo'),
        ]
        selected = None
        for candidate in candidates:
            if isinstance(candidate, str) and candidate:
                convo_dir = self.get_convo_path(candidate)
                if convo_dir.exists() and convo_dir.is_dir():
                    selected = candidate
                    break

        self.current_convo = selected

    def save_context_state(self):
        try:
            context_convos_dir = self.get_context_convos_dir()
            context_convos_dir.mkdir(parents=True, exist_ok=True)
            context_state_file = self.get_context_state_file()
            with open(context_state_file, 'w') as f:
                json.dump(self.current_context_state, f, indent=2, sort_keys=True)
        except Exception:
            return

    def set_context_convo(self, convo_id: Optional[str]):
        self.current_convo = convo_id

        if not isinstance(getattr(self, 'current_context_state', None), dict):
            self.current_context_state = {}

        self.current_context_state['last_convo'] = convo_id

        self.save_context_state()

    def apply_manual_injections_from_context_state(self):
        if not isinstance(getattr(self, 'current_context_state', None), dict):
            return

        manual = self.current_context_state.get('manual_inject')
        if not isinstance(manual, list):
            return

        seen = {inj.get('file') for inj in self.injected_files if isinstance(inj, dict)}
        for file_path in manual:
            if not isinstance(file_path, str):
                continue
            if file_path in seen:
                continue
            self.injected_files.append({
                'file': file_path,
                'injected_at': datetime.datetime.now().isoformat() + 'Z'
            })
            seen.add(file_path)
    
    def load_config(self, config_path: str = None) -> Dict:
        """Load configuration from YAML file with defaults."""

        cur_dir = os.getcwd()

        # Default configuration
        default_config = {
            'default_model': 'firmen102/qwen3.5-27b',
            'default_endpoint': 'ollama',
            'endpoints': {
                'openai': {
                    'url': 'https://api.openai.com/v1',
                    'key_env': 'OPENAI_API_KEY'
                },
                'ollama': {
                    'url': 'http://localhost:11434/v1',
                    'key_env': None
                },
                'vllm': {
                    'url': 'http://localhost:8000/v1',
                    'key_env': None
                }
            },
            'lab_root': cur_dir,
            'conversation_store': 'infra/convos',
            'prompt_library': 'infra/prompts',
            'auto_inject_makefile': True
        }
        
        if config_path is None:
            # reasonable default
            config_path = Path(cur_dir) / 'infra' / 'config' / 'chat.yaml'
        
        # Load config file if it exists
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                loaded_config = pyyaml.safe_load(f)
            # Merge with defaults (loaded config takes precedence)
            default_config.update(loaded_config)
        
        return default_config
    
    def setup_openai(self):
        """Setup OpenAI client for current endpoint."""
        endpoint_config = self.config['endpoints'][self.current_endpoint]
        
        if self.current_endpoint == 'openai':
            api_key = os.getenv(endpoint_config['key_env'])
            if not api_key:
                raise ValueError(f"Missing {endpoint_config['key_env']} environment variable")
            self.client = openai.OpenAI(api_key=api_key, base_url=endpoint_config['url'])
        else:
            # Local endpoint (Ollama)
            self.client = openai.OpenAI(base_url=endpoint_config['url'], api_key='not-needed')
    
    def setup_history(self):
        """Setup command line history persistence."""
        # Create ~/.lab directory if it doesn't exist
        self.lab_home.mkdir(exist_ok=True)
        
        # History file path
        self.history_file = self.lab_home / '.cli-history'
        
        # Load existing history
        if self.history_file.exists():
            readline.read_history_file(str(self.history_file))
        
        # Set history length
        readline.set_history_length(1000)
        
        # Save history on exit
        import atexit
        atexit.register(self.save_history)
    
    def save_history(self):
        """Save command line history to file."""
        try:
            readline.write_history_file(str(self.history_file))
        except Exception as e:
            # Don't crash on history save errors
            pass
    
    def setup_completion(self):
        """Setup readline tab completion."""
        commands = ['/convo', '/switch', '/prompts', '/prompt', '/inject', '/model', '/show', '/help', '/quit']
        
        def completer(text, state):
            options = []
            if text.startswith('/'):
                options = [cmd for cmd in commands if cmd.startswith(text)]
            else:
                # File completion for non-commands
                try:
                    path = str(self.current_context)
                    files = glob.glob(os.path.join(path, text + '*'))
                    options = [os.path.basename(f) for f in files if os.path.isfile(f)]
                except:
                    pass
            
            if state < len(options):
                return options[state]
            return None
        
        readline.set_completer(completer)
        readline.parse_and_bind('tab: complete')
    
    def get_convo_path(self, convo_id: str) -> Path:
        """Get path to conversation directory."""
        return self.convos_dir / convo_id
    
    def get_next_file_number(self, convo_dir: Path) -> str:
        """Get next sequence number for conversation file."""
        existing = list(convo_dir.glob('*.yaml'))
        if not existing:
            return '0001'
        
        # Extract numeric part from filenames like "0001-meta.yaml"
        numbers = []
        for f in existing:
            stem = f.stem
            if '-' in stem:
                num_part = stem.split('-')[0]
            else:
                num_part = stem
            try:
                numbers.append(int(num_part))
            except ValueError:
                continue
        
        if not numbers:
            return '0001'
        
        max_num = max(numbers)
        return f"{max_num + 1:04d}"
    
    def write_convo_file(self, convo_dir: Path, content: Any, file_type: str):
        """Write a conversation file and make it immutable."""
        filename = f"{self.get_next_file_number(convo_dir)}-{file_type}.yaml"
        filepath = convo_dir / filename
        
        with open(filepath, 'w') as f:
            pyyaml.dump(content, f, default_flow_style=False)

        # Make immutable
        os.chmod(filepath, self.PERM_IMMUTABLE)

    def build_meta_state(self, *, include_title: bool = False, title: Optional[str] = None, convo_id: Optional[str] = None) -> Dict[str, Any]:
        context_rel = str(self.current_context.resolve())
        try:
            context_rel = str(self.current_context.relative_to(self.lab_root))
        except Exception:
            pass

        injected_yaml_mtime = None
        try:
            injected_yaml_path = self.current_context / 'injected.yaml'
            if injected_yaml_path.exists():
                injected_yaml_mtime = injected_yaml_path.stat().st_mtime
        except Exception:
            injected_yaml_mtime = None

        payload: Dict[str, Any] = {
            'timestamp': datetime.datetime.now().isoformat() + 'Z',
            'context': context_rel,
            'model': self.current_model,
            'endpoint': self.current_endpoint,
            'injected_yaml_mtime': injected_yaml_mtime,
            'prompts': [
                {
                    'prompt': prompt['name'],
                    'version': prompt['version'],
                    'snapshot': prompt['snapshot']
                } for prompt in self.current_prompts
            ],
            'injected_files': [
                {
                    'file': injected['file'],
                    'injected_at': injected.get('injected_at')
                } for injected in self.injected_files
            ]
        }

        if convo_id is not None:
            payload['uuid'] = convo_id

        if include_title:
            if title is not None:
                payload['title'] = title

        return payload

    def compute_auto_injected_files(self) -> List[Dict[str, Any]]:
        injected_files: List[Dict[str, Any]] = []

        if self.config.get('auto_inject_makefile', True):
            makefile_path = self.current_context / 'Makefile'
            if makefile_path.exists():
                injected_files.append({
                    'file': str(makefile_path.relative_to(self.lab_root)),
                    'injected_at': datetime.datetime.now().isoformat() + 'Z'
                })

        injected_yaml_path = self.current_context / 'injected.yaml'
        if injected_yaml_path.exists():
            try:
                with open(injected_yaml_path, 'r') as f:
                    injected_config = pyyaml.safe_load(f)
            except Exception:
                injected_config = None

            if isinstance(injected_config, list):
                for item in injected_config:
                    if not isinstance(item, dict):
                        continue
                    if item.get('auto', True):
                        file_str = item.get('file')
                        if not isinstance(file_str, str):
                            continue
                        file_path = self.lab_root / file_str
                        if file_path.exists():
                            injected_files.append({
                                'file': file_str,
                                'injected_at': datetime.datetime.now().isoformat() + 'Z'
                            })

        return injected_files

    def refresh_injected_files(self, *, notify: bool, record_meta: bool):
        prev_set = self.last_injected_set or {inj.get('file') for inj in self.injected_files if isinstance(inj, dict)}

        injected_files = self.compute_auto_injected_files()

        manual = None
        if isinstance(getattr(self, 'current_context_state', None), dict):
            manual = self.current_context_state.get('manual_inject')

        if isinstance(manual, list):
            seen = {inj.get('file') for inj in injected_files if isinstance(inj, dict)}
            for file_path in manual:
                if not isinstance(file_path, str):
                    continue
                if file_path in seen:
                    continue
                injected_files.append({
                    'file': file_path,
                    'injected_at': datetime.datetime.now().isoformat() + 'Z'
                })
                seen.add(file_path)

        new_set = {inj.get('file') for inj in injected_files if isinstance(inj, dict)}
        added = sorted([p for p in (new_set - prev_set) if isinstance(p, str)])
        removed = sorted([p for p in (prev_set - new_set) if isinstance(p, str)])

        self.injected_files = injected_files
        self.last_injected_set = new_set

        if not added and not removed:
            return

        if notify:
            msg_parts = []
            if added:
                msg_parts.append(f"+{len(added)}")
            if removed:
                msg_parts.append(f"-{len(removed)}")
            summary = ' '.join(msg_parts) if msg_parts else '0'
            detail = []
            if added:
                detail.append('+' + ', +'.join(added))
            if removed:
                detail.append('-' + ', -'.join(removed))
            detail_str = (' ' + ' '.join(detail)) if detail else ''
            print(f"Injected set changed ({summary}){detail_str}")

        if record_meta and self.current_convo:
            event_meta: Dict[str, Any] = {
                'timestamp': datetime.datetime.now().isoformat() + 'Z',
                'event': 'injected_set_changed',
                'context': str(self.current_context.relative_to(self.lab_root)),
                'added': added,
                'removed': removed,
            }
            try:
                injected_yaml_path = self.current_context / 'injected.yaml'
                if injected_yaml_path.exists():
                    event_meta['injected_yaml_mtime'] = injected_yaml_path.stat().st_mtime
            except Exception:
                pass
            self.write_convo_meta(self.current_convo, event_meta)

    def write_convo_meta(self, convo_id: str, meta: Dict[str, Any]):
        convo_dir = self.get_convo_path(convo_id)
        self.write_convo_file(convo_dir, meta, 'meta')

    def write_meta_update(self):
        if not self.current_convo:
            return

        convo_dir = self.get_convo_path(self.current_convo)
        meta = self.build_meta_state(convo_id=self.current_convo)
        self.write_convo_file(convo_dir, meta, 'meta')
    
    def create_convo(self, name: str = None) -> str:
        """Create a new conversation."""
        convo_id = str(uuid.uuid4())
        convo_dir = self.get_convo_path(convo_id)
        convo_dir.mkdir(exist_ok=True)
        
        if name is None:
            name = f"convo-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        meta = self.build_meta_state(include_title=True, title=name, convo_id=convo_id)
        meta['fork_of'] = None
        meta['fork_at'] = None
        meta['tags'] = []
        meta['status'] = 'active'
        
        self.write_convo_file(convo_dir, meta, 'meta')
        
        # Create symlink in current context
        self.create_convo_symlink(convo_id, name)
        
        self.set_context_convo(convo_id)
        if not self.first_convo:
            self.first_convo = convo_id
        self.save_state()
        return convo_id
    
    def create_convo_symlink(self, convo_id: str, name: str):
        """Create symlink to conversation in current context."""
        context_convos_dir = self.current_context / 'convos'
        context_convos_dir.mkdir(exist_ok=True)
        
        # Sanitize name for filename
        safe_name = name.lower().replace(' ', '-').replace('/', '-')
        symlink_path = context_convos_dir / f"{safe_name}.yaml"
        target_path = self.get_convo_path(convo_id)
        
        # Remove existing symlink if it exists
        if symlink_path.exists():
            symlink_path.unlink()
        
        # Create relative symlink
        relative_target = os.path.relpath(target_path, context_convos_dir)
        symlink_path.symlink_to(relative_target)
    
    def load_prompt(self, prompt_name: str) -> Dict:
        """Load a prompt from the prompt library."""
        prompt_path = None
        
        # Search in system, templates, then workflows
        for subdir in ['system', 'templates', 'workflows']:
            candidate = self.prompts_dir / subdir / f"{prompt_name}.md"
            if candidate.exists():
                prompt_path = candidate
                break
        
        if not prompt_path:
            raise ValueError(f"Prompt '{prompt_name}' not found")
        
        with open(prompt_path, 'r') as f:
            content = f.read()
        
        # Parse frontmatter
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                frontmatter = pyyaml.safe_load(parts[1])
                body = parts[2].strip()
                return {
                    'name': frontmatter['title'],
                    'version': frontmatter['version'],
                    'snapshot': body,
                    'frontmatter': frontmatter
                }
        
        raise ValueError(f"Invalid prompt format in {prompt_name}")
    
    def inject_files(self):
        """Inject configured files into context."""
        self.injected_files.extend(self.compute_auto_injected_files())
    
    def build_context(self) -> str:
        """Build the full context for the AI."""
        context_parts = []
        
        # Add prompts
        for prompt in self.current_prompts:
            context_parts.append(f"=== PROMPT: {prompt['name']} v{prompt['version']} ===")
            context_parts.append(prompt['snapshot'])
            context_parts.append("")
        
        # Add injected files
        for injected in self.injected_files:
            context_parts.append(f"<injected file=\"{injected['file']}\" injected_at=\"{injected['injected_at']}\">")
            full_path = self.lab_root / injected['file']
            try:
                with open(full_path, 'r') as f:
                    context_parts.append(f.read())
            except Exception as e:
                context_parts.append(f"Error reading injected file: {e}")
            context_parts.append("</injected>")
            context_parts.append("")
        
        # Add context info
        context_parts.append(f"=== CURRENT CONTEXT ===")
        context_parts.append(f"Directory: {self.current_context.relative_to(self.lab_root)}")
        context_parts.append(f"Conversation: {self.current_convo or 'None'}")
        context_parts.append(f"Model: {self.current_model} ({self.current_endpoint})")
        context_parts.append("")
        
        return "\n".join(context_parts)
    
    def send_message(self, message: str) -> str:
        """Send a message to the AI and get response."""
        if not self.current_convo:
            self.create_convo()

        self.refresh_injected_files(notify=True, record_meta=True)
        
        convo_dir = self.get_convo_path(self.current_convo)
        
        # Write user message
        user_msg = [{
            'role': 'user',
            'content': message,
            'timestamp': datetime.datetime.now().isoformat() + 'Z'
        }]
        self.write_convo_file(convo_dir, user_msg, 'user')
        
        # Build full context
        full_context = self.build_context()
        
        # Add conversation history
        history = self.load_convo_history()
        messages = []
        
        # Add system context
        messages.append({'role': 'system', 'content': full_context})
        
        # Add history
        for msg in history:
            if msg['role'] in ['user', 'assistant']:
                messages.append({'role': msg['role'], 'content': msg['content']})
        
        # Add current message
        messages.append({'role': 'user', 'content': message})
        
        # Get AI response
        try:
            response = self.client.chat.completions.create(
                model=self.current_model,
                messages=messages,
                temperature=0.7
            )
            ai_response = response.choices[0].message.content
        except Exception as e:
            ai_response = f"Error: {str(e)}"
        
        # Write AI response
        asst_msg = [{
            'role': 'asst',
            'content': ai_response,
            'timestamp': datetime.datetime.now().isoformat() + 'Z'
        }]
        self.write_convo_file(convo_dir, asst_msg, 'asst')
        
        return ai_response
    
    def load_convo_history(self) -> List[Dict]:
        """Load conversation history."""
        if not self.current_convo:
            return []
        
        convo_dir = self.get_convo_path(self.current_convo)
        history = []
        
        for filepath in sorted(convo_dir.glob('*.yaml')):
            if filepath.name.endswith('-meta.yaml'):
                continue
            
            with open(filepath, 'r') as f:
                content = pyyaml.safe_load(f)
            
            if isinstance(content, list) and content:
                history.extend(content)
        
        return history
    
    def handle_command(self, line: str) -> bool:
        """Handle slash commands. Returns True if command was handled."""
        if not line.startswith('/'):
            return False
        
        parts = line.split()
        command = parts[0]
        args = parts[1:] if len(parts) > 1 else []
        
        if command == '/help':
            self.show_help()
        elif command == '/show':
            self.handle_show(args)
        elif command == '/quit' or command == '/exit':
            print("Goodbye!")
            sys.exit(0)
        elif command == '/convo':
            self.handle_convo(args)
        elif command == '/switch':
            self.handle_switch(args)
        elif command == '/prompts':
            self.handle_prompts()
        elif command == '/prompt':
            self.handle_prompt(args)
        elif command == '/inject':
            self.handle_inject(args)
        elif command == '/model':
            self.handle_model(args)
        elif command == '/status':
            self.show_status()
        elif command == '/history':
            self.show_history()
        else:
            print(f"Unknown command: {command}")
        
        return True
    
    def handle_convo(self, args: List[str]):
        """Handle conversation commands."""
        if not args:
            # List conversations in current context
            convos_dir = self.current_context / 'convos'
            if convos_dir.exists():
                print("Conversations in this context:")
                for symlink in convos_dir.glob('*.yaml'):
                    if symlink.is_symlink():
                        target = symlink.readlink()
                        print(f"  {symlink.stem} -> {target}")
            else:
                print("No conversations in this context")
            return
        
        if args[0] == 'list':
            self.handle_convo([])
        elif args[0] == 'new':
            name = args[1] if len(args) > 1 else None
            convo_id = self.create_convo(name)
            print(f"Created conversation: {convo_id}")
        elif args[0] == 'fork':
            if not self.current_convo:
                print("No conversation to fork")
                return
            name = args[1] if len(args) > 1 else None
            # TODO: Implement forking
            print("Forking not yet implemented")
        else:
            # Switch to existing conversation
            convo_name = args[0]
            convos_dir = self.current_context / 'convos'
            symlink_path = convos_dir / f"{convo_name}.yaml"
            
            if symlink_path.exists() and symlink_path.is_symlink():
                target = symlink_path.readlink()
                convo_id = target.name
                self.set_context_convo(convo_id)
                self.save_state()
                print(f"Switched to conversation: {convo_name}")
            else:
                print(f"Conversation '{convo_name}' not found")
    
    def handle_show(self, args: List[str]):
        """Handle show commands."""
        if not args:
            print("Usage: /show <subcommand>")
            print("  config   - Show current configuration")
            print("  status   - Show current status")
            print("  history  - Show conversation history")
            return
        
        subcommand = args[0]
        
        if subcommand == 'config':
            self.show_config()
        elif subcommand == 'status':
            self.show_status()
        elif subcommand == 'history':
            self.show_history()
        else:
            print(f"Unknown show subcommand: {subcommand}")
            print("Available: config, status, history")
    
    def show_config(self):
        """Show current configuration."""
        print("Current Configuration:")
        print(f"  Model: {self.current_model} ({self.current_endpoint})")
        print(f"  Lab Root: {self.lab_root}")
        print(f"  Context: {self.current_context.relative_to(self.lab_root)}")
        print(f"  Conversation Store: {self.convos_dir}")
        print(f"  Prompt Library: {self.prompts_dir}")
        print(f"  Auto-inject Makefile: {self.config.get('auto_inject_makefile', True)}")
        print(f"  History File: {self.history_file}")
        
        if self.current_convo:
            print(f"  Current Conversation: {self.current_convo}")
        else:
            print("  Current Conversation: None")
        
        if self.current_prompts:
            print(f"  Active Prompts: {len(self.current_prompts)}")
            for prompt in self.current_prompts:
                print(f"    - {prompt['name']} v{prompt['version']}")
        else:
            print("  Active Prompts: None")
        
        if self.injected_files:
            print(f"  Injected Files: {len(self.injected_files)}")
            for injected in self.injected_files:
                print(f"    - {injected['file']}")
        else:
            print("  Injected Files: None")
    
    def handle_switch(self, args: List[str]):
        """Handle context switching."""
        if not args:
            # List available contexts
            print("Available contexts:")
            for item in self.lab_root.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    rel_path = item.relative_to(self.lab_root)
                    marker = " (current)" if item == self.current_context else ""
                    print(f"  {rel_path}{marker}")
            return
        
        if args[0] == 'list':
            self.handle_switch([])
            return
        
        # Switch to specific context
        old_convo = self.current_convo
        old_context_rel = str(self.current_context.resolve())
        try:
            old_context_rel = str(self.current_context.relative_to(self.lab_root))
        except Exception:
            pass

        new_context = self.lab_root / args[0]
        if new_context.exists() and new_context.is_dir():
            self.current_context = new_context
            self.injected_files = []
            self.load_context_state()
            self.inject_files()
            self.apply_manual_injections_from_context_state()
            self.last_injected_set = {inj.get('file') for inj in self.injected_files if isinstance(inj, dict)}
            self.save_state()

            new_convo = self.current_convo
            new_context_rel = str(self.current_context.resolve())
            try:
                new_context_rel = str(self.current_context.relative_to(self.lab_root))
            except Exception:
                pass

            if old_convo:
                leave_meta: Dict[str, Any] = {
                    'timestamp': datetime.datetime.now().isoformat() + 'Z',
                    'event': 'switch_context',
                    'from_context': old_context_rel,
                    'to_context': new_context_rel,
                    'to_convo': new_convo,
                }
                self.write_convo_meta(old_convo, leave_meta)
            print(f"Switched to context: {new_context.relative_to(self.lab_root)}")
        else:
            print(f"Context '{args[0]}' not found")
    
    def handle_prompts(self):
        """List available prompts."""
        print("Available prompts:")
        for subdir in ['system', 'templates', 'workflows']:
            subdir_path = self.prompts_dir / subdir
            if subdir_path.exists():
                print(f"\n{subdir.title()}:")
                for prompt_file in subdir_path.glob('*.md'):
                    print(f"  {prompt_file.stem}")
    
    def handle_prompt(self, args: List[str]):
        """Handle prompt management."""
        if not args:
            print("Current prompts:")
            for prompt in self.current_prompts:
                print(f"  {prompt['name']} v{prompt['version']}")
            return
        
        if args[0] == 'add':
            if len(args) < 2:
                print("Usage: /prompt add <prompt_name>")
                return
            prompt_name = args[1]
            try:
                prompt = self.load_prompt(prompt_name)
                self.current_prompts.append(prompt)
                self.write_meta_update()
                print(f"Added prompt: {prompt_name}")
            except ValueError as e:
                print(f"Error: {e}")
        elif args[0] == 'drop':
            if len(args) < 2:
                print("Usage: /prompt drop <prompt_name>")
                return
            prompt_name = args[1]
            self.current_prompts = [p for p in self.current_prompts if p['name'] != prompt_name]
            self.write_meta_update()
            print(f"Dropped prompt: {prompt_name}")
        else:
            print("Unknown prompt command. Use: add, drop")
    
    def handle_inject(self, args: List[str]):
        """Handle file injection."""
        if not args:
            print("Currently injected files:")
            for injected in self.injected_files:
                print(f"  {injected['file']}")
            return
        
        if args[0] == 'list':
            self.handle_inject([])
        elif args[0] == 'clear':
            self.injected_files = []
            self.inject_files()
            if not isinstance(getattr(self, 'current_context_state', None), dict):
                self.current_context_state = {}
            self.current_context_state['manual_inject'] = []
            self.save_context_state()
            self.write_meta_update()
            print("Cleared injected files")
        elif args[0] == 'drop':
            if len(args) < 2:
                print("Usage: /inject drop <file>")
                return
            file_path = args[1]
            self.injected_files = [f for f in self.injected_files if f['file'] != file_path]
            if isinstance(getattr(self, 'current_context_state', None), dict):
                manual = self.current_context_state.get('manual_inject')
                if isinstance(manual, list):
                    self.current_context_state['manual_inject'] = [p for p in manual if p != file_path]
                    self.save_context_state()
            self.write_meta_update()
            print(f"Dropped injected file: {file_path}")
        else:
            # Inject specific file
            file_path = args[0]
            full_path = self.lab_root / file_path
            if full_path.exists():
                self.injected_files.append({
                    'file': file_path,
                    'injected_at': datetime.datetime.now().isoformat() + 'Z'
                })
                if not isinstance(getattr(self, 'current_context_state', None), dict):
                    self.current_context_state = {}
                manual = self.current_context_state.get('manual_inject')
                if not isinstance(manual, list):
                    manual = []
                if file_path not in manual:
                    manual.append(file_path)
                self.current_context_state['manual_inject'] = manual
                self.save_context_state()
                self.write_meta_update()
                print(f"Injected file: {file_path}")
            else:
                print(f"File '{file_path}' not found")
    
    def handle_model(self, args: List[str]):
        """Handle model management."""
        if not args:
            print(f"Current model: {self.current_model} ({self.current_endpoint})")
            return
        
        if args[0] == 'list':
            print("Available endpoints:")
            for endpoint in self.config['endpoints']:
                print(f"  {endpoint}")
            return
        
        # Switch model
        model_name = args[0]
        if ':' in model_name:
            model_name, endpoint = model_name.split(':', 1)
            if endpoint in self.config['endpoints']:
                self.current_endpoint = endpoint
                self.setup_openai()
            else:
                print(f"Unknown endpoint: {endpoint}")
                return
        
        self.current_model = model_name
        self.write_meta_update()
        print(f"Switched to model: {model_name} ({self.current_endpoint})")
    
    def show_status(self):
        """Show current status."""
        print(f"context: {self.current_context.relative_to(self.lab_root)}")
        print(f"convo:   {self.current_convo or 'None'}")
        if self.current_prompts:
            prompts_str = ', '.join([f"{p['name']} v{p['version']}" for p in self.current_prompts])
            print(f"prompts: {prompts_str}")
        print(f"model:   {self.current_model} ({self.current_endpoint})")
        
        if self.current_convo:
            history = self.load_convo_history()
            message_count = len([msg for msg in history if msg['role'] in ['user', 'asst']])
            print(f"messages: {message_count}")
    
    def show_history(self):
        """Show conversation history."""
        if not self.current_convo:
            print("No active conversation")
            return
        
        history = self.load_convo_history()
        for msg in history:
            if msg['role'] == 'user':
                print(f"User: {msg['content']}")
            elif msg['role'] == 'asst':
                print(f"Assistant: {msg['content']}")
            print()
    
    def show_help(self):
        """Show help information."""
        print(HELP_MESSAGE)
    
    def get_status_line(self) -> str:
        """Generate status line for display."""
        parts = []
        parts.append(f"context: {self.current_context.relative_to(self.lab_root)}")
        
        if self.current_convo:
            convo_dir = self.get_convo_path(self.current_convo)
            meta_file = convo_dir / '0001-meta.yaml'
            if meta_file.exists():
                with open(meta_file, 'r') as f:
                    meta = pyyaml.safe_load(f)
                parts.append(f"convo: {meta['title']} ({self.current_convo[:8]})")
        
        if self.current_prompts:
            prompts_str = ', '.join([f"{p['name']}" for p in self.current_prompts])
            parts.append(f"prompts: {prompts_str}")
        
        parts.append(f"model: {self.current_model}")
        
        if self.current_convo:
            history = self.load_convo_history()
            message_count = len([msg for msg in history if msg['role'] in ['user', 'asst']])
            parts.append(f"messages: {message_count}")
        
        return ' | '.join(parts)
    
    def run(self):
        """Main chat loop."""
        print("Welcome to Lab Infra Chat CLI")
        print("Type /help for commands, /quit to exit")
        print()
        
        # Inject initial files
        self.inject_files()
        
        while True:
            try:
                # Show status
                status = self.get_status_line()
                print(f"\n{status}")
                
                # Get input
                line = input(">>> ").strip()
                
                if not line:
                    continue
                
                # Handle commands
                if self.handle_command(line):
                    continue
                
                # Send message and show response
                response = self.send_message(line)
                print(f"\n{response}")
                
            except KeyboardInterrupt:
                print("\nUse /quit to exit")
            except EOFError:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"Error: {e}")

def main():
    """Main entry point for the CLI."""
    args = docopt(__doc__, version=f'Lab Infra Chat CLI {__version__}')
    
    config_path = args.get('--config')
    if config_path == 'infra/config/chat.yaml':
        # Default path - let the CLI figure out the full path
        config_path = None
    
    cli = ChatCLI(config_path)
    cli.run()

if __name__ == '__main__':
    main()
