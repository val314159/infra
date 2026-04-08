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
  /show status            Show current state
  /show history           Show conversation history
  /status                 Alias for /show status
  /history                Alias for /show history
  !<cmd>                  Run a shell command in the current context
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
import glob
import subprocess
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import openai
from docopt import docopt
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from .tools import __index__ as tool_index

class ChatCLI:
    # Unix permission constants (core architectural choices)
    PERM_IMMUTABLE = 0o444  # read-only for all
    PERM_MUTABLE = 0o644    # read-write for owner, read-only for others
    PERM_DIRECTORY = 0o755  # read/write/execute for owner, read/execute for others

    def ensure_dir(self, path: Path) -> None:
        """Ensure directory exists."""
        path.mkdir(parents=True, exist_ok=True)
    
    def load_json_file(self, file_path: Path, default: Any = None) -> Any:
        """Load JSON file with default and error handling."""
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return default
        except Exception:
            print(f"Warning: Failed to load {file_path}")
            return default
    
    def save_json_file(self, file_path: Path, data: Any) -> bool:
        """Save JSON file with error handling."""
        try:
            self.ensure_dir(file_path.parent)
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2, sort_keys=True)
            return True
        except Exception:
            print(f"Warning: Failed to save {file_path}")
            return False

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

        self.current_context = Path.cwd()
        self.convos_dir = self.lab_home / 'convos'
        self.prompts_dir = self.lab_home / 'prompts'
        self.state_file = self.lab_home / 'chat_state.json'
        self.first_convo: Optional[str] = None
        
        # Current state
        self.current_convo = None
        self.current_prompts = []
        self.current_model = self.config['default_model']
        self.current_endpoint = self.config['default_endpoint']
        self.retry_message: Optional[str] = ''

        self.restore_last_convo = bool(self.config.get('restore_last_convo', True))

        # Initialize context state before loading
        self.current_context_state = {}

        self.load_user_state()
        self.load_context_state()
        
        # Ensure directories exist
        self.ensure_dir(self.convos_dir)
        
        # Setup history and prompt tooling
        self.setup_history()
        self.setup_completion()

        # Setup OpenAI client
        endpoint_config = self.config['endpoints'][self.current_endpoint]        
        if (api_key := endpoint_config['key_env']).isupper():
            if not (api_key := os.getenv(api_key)):
                raise ValueError(f"Missing {api_key} environment variable")
        self.client = openai.OpenAI(api_key=api_key, base_url=endpoint_config['url'])
        
    def load_user_state(self):
        state = self.load_json_file(self.state_file)
        if state is None:
            return

        ctx = state.get('last_context')
        if isinstance(ctx, str):
            candidate = Path(ctx)
            if not candidate.is_absolute():
                candidate = Path.cwd() / ctx

            if candidate.exists() and candidate.is_dir():
                self.set_current_context(candidate)  # Use centralized method to chdir

        fc = state.get('first_convo')
        if isinstance(fc, str) and fc:
            self.first_convo = fc

    def save_user_state(self):
        state = {
            'last_context': str(self.current_context.resolve()),
            'first_convo': self.first_convo,
            'saved_at': datetime.datetime.now().isoformat() + 'Z',
        }
        self.save_json_file(self.state_file, state)

    def set_current_context(self, new_context: Path):
        """Set current context and change working directory."""
        old_context = self.current_context
        self.current_context = new_context
        os.chdir(new_context)  # Single place for chdir
        
        # Save the change
        self.save_context_state()
        self.save_user_state()
        
        return old_context

    def load_context_state(self):
        context_state_file = self.get_context_state_file()
        
        state = self.load_json_file(context_state_file, {})
        if not isinstance(state, dict):
            state = {}

        self.current_context_state = state

        # Find last conversation for this context
        last_convo = state.get('last_convo')
        if isinstance(last_convo, str) and last_convo:
            candidates = [last_convo]
        else:
            candidates = []

        # Try to find a valid conversation
        selected = None
        for candidate in candidates:
            if isinstance(candidate, str) and candidate:
                convo_dir = self.get_convo_path(candidate)
                if convo_dir.exists() and convo_dir.is_dir():
                    selected = candidate
                    break

        self.current_convo = selected
        
        # If we have a saved context directory, change to it
        saved_context = state.get('context_directory')
        if saved_context and Path(saved_context).exists():
            self.set_current_context(Path(saved_context))

    def save_context_state(self):
        context_convos_dir = self.get_context_convos_dir()
        context_state_file = self.get_context_state_file()
        
        # Save current context directory for restoration
        self.current_context_state['context_directory'] = str(self.current_context)
        
        self.save_json_file(context_state_file, self.current_context_state)

    def set_context_convo(self, convo_id: Optional[str]):
        self.current_convo = convo_id

        if not isinstance(getattr(self, 'current_context_state', None), dict):
            self.current_context_state = {}

        self.current_context_state['last_convo'] = convo_id

        self.save_context_state()

    def load_config(self, config_path: str = None) -> Dict:
        """Load configuration from YAML file with defaults."""
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
                    'key_env': 'dummy'
                }
            },
            'auto_inject_makefile': True,   
            'restore_last_convo': True
        }

        # Load user config from ~/.lab/config.yaml
        user_config_path = self.lab_home / 'config.yaml'
        if user_config_path.exists():
            try:
                with open(user_config_path, 'r') as f:
                    loaded_config = pyyaml.safe_load(f)
                default_config.update(loaded_config)
            except Exception:
                print(f"Warning: Failed to load config from {user_config_path}")
        else:
            # Write default config so user can see what's available
            try:
                self.ensure_dir(self.lab_home)
                with open(user_config_path, 'w') as f:
                    pyyaml.dump(default_config, f, indent=2)
                print(f"Created default config at: {user_config_path}")
            except Exception:
                print(f"Warning: Failed to create default config at {user_config_path}")
        
        # Override with explicit config path if provided
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    loaded_config = pyyaml.safe_load(f)
                default_config.update(loaded_config)
            except Exception:
                print(f"Warning: Failed to load config from {config_path}")
        
        return default_config
    
    def setup_completion(self):
        """Setup prompt-toolkit tab completion."""
        commands = ['/convo', '/switch', '/prompts', '/prompt', '/inject', '/model', '/show', '/help', '/quit']

        class ChatCompleter(Completer):
            def get_completions(self, document, complete_event):
                text = document.text_before_cursor
                words = text.split()
                
                # No input - complete commands
                if not text:
                    for cmd in commands:
                        yield Completion(cmd, start_position=0)
                    return
                
                # Complete command names
                if len(words) == 1 and text.startswith('/'):
                    for cmd in commands:
                        if cmd.startswith(text):
                            yield Completion(cmd, start_position=-len(text))
                    return
                
                # Complete command arguments
                if len(words) >= 2 and words[0].startswith('/'):
                    cmd = words[0]
                    current_arg = words[-1]
                    start_pos = -len(current_arg)
                    
                    try:
                        if cmd == '/switch':
                            # Complete directories from current working directory
                            base_path = Path.cwd()
                            for item in base_path.glob(current_arg + '*'):
                                if item.is_dir():
                                    rel_path = str(item.relative_to(base_path))
                                    yield Completion(rel_path, start_position=start_pos)
                        
                        elif cmd == '/inject':
                            # Complete files and directories
                            if current_arg.startswith('./'):
                                # Current context relative
                                base_path = self_outer.current_context
                                search_pattern = current_arg[2:] + '*'
                                for item in base_path.glob(search_pattern):
                                    rel_path = './' + str(item.relative_to(base_path))
                                    yield Completion(rel_path, start_position=start_pos)
                            elif current_arg.startswith('/'):
                                # Absolute path completion
                                if '/' in current_arg:
                                    base_path = Path(current_arg).parent
                                    search_pattern = Path(current_arg).name + '*'
                                    if base_path.exists():
                                        for item in base_path.glob(search_pattern):
                                            yield Completion(str(item), start_position=start_pos)
                            else:
                                # Relative to current working directory
                                base_path = Path.cwd()
                                for item in base_path.glob(current_arg + '*'):
                                    rel_path = str(item.relative_to(base_path))
                                    yield Completion(rel_path, start_position=start_pos)
                    
                    except Exception:
                        pass  # Silently fail completion
                
                return

        self_outer = self
        self.prompt_completer = ChatCompleter()
        self.session = PromptSession(history=self.prompt_history, completer=self.prompt_completer)
    
    def setup_history(self):
        """Setup command line history persistence."""
        # History file path
        self.history_file = self.lab_home / '.cli-history'
        self.ensure_dir(self.history_file.parent)
        self.prompt_history = FileHistory(str(self.history_file))

    def append_history_line(self, line: str):
        if not line:
            return
        try:
            with open(self.history_file, 'a', encoding='utf-8') as f:
                f.write(line.replace('\n', ' ') + '\n')
                f.flush()
                os.fsync(f.fileno())
                return
        except Exception:
            print(f"Warning: Failed to write history file: {self.history_file}")
            return

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
                print(f"Warning: Failed to parse number from {num_part}")
                continue
        
        if not numbers:
            return '0001'
        
        max_num = max(numbers)
        return f"{max_num + 1:04d}"

    def build_meta_state(self, *, include_title: bool = False, title: Optional[str] = None, convo_id: Optional[str] = None) -> Dict[str, Any]:
        context_rel = str(self.current_context)

        payload: Dict[str, Any] = {
            'timestamp': datetime.datetime.now().isoformat() + 'Z',
            'context': context_rel,
            'model': self.current_model,
            'endpoint': self.current_endpoint,
            'prompts': [
                {
                    'prompt': prompt['name'],
                    'version': prompt['version'],
                    'snapshot': prompt['snapshot']
                } for prompt in self.current_prompts
            ]
        }

        if convo_id is not None:
            payload['uuid'] = convo_id

        if include_title:
            if title is not None:
                payload['title'] = title

        return payload

    def build_context(self) -> str:
        """Build the full context for the AI."""
        context_parts = []
        
        # Add prompts
        for prompt in self.current_prompts:
            context_parts.append(f"=== PROMPT: {prompt['name']} v{prompt['version']} ===")
            context_parts.append(prompt['snapshot'])
            context_parts.append("")
        
        # Add injected files
        for injected in self.get_injected_files():
            context_parts.append(f"<injected file=\"{injected['file']}\" injected_at=\"{injected['injected_at']}\">")
            full_path = Path(injected['file'])
            try:
                with open(full_path, 'r') as f:
                    context_parts.append(f.read())
            except Exception as e:
                context_parts.append(f"Error reading injected file: {e}")
            context_parts.append("</injected>")
            context_parts.append("")
        
        # Add context info
        context_parts.append(f"=== CURRENT CONTEXT ===")
        context_parts.append(f"Directory: {self.current_context}")
        context_parts.append(f"Conversation: {self.current_convo or 'None'}")
        context_parts.append(f"Model: {self.current_model} ({self.current_endpoint})")
        context_parts.append("")
        
        return "\n".join(context_parts)

    def write_convo_file(self, convo_dir: Path, content: Any, file_type: str):
        """Write a conversation file and make it immutable."""
        filename = f"{self.get_next_file_number(convo_dir)}-{file_type}.yaml"
        filepath = convo_dir / filename
        
        with open(filepath, 'w') as f:
            pyyaml.dump(content, f, default_flow_style=False)

        # Make immutable
        os.chmod(filepath, self.PERM_IMMUTABLE)

    def write_meta_update(self):
        if not self.current_convo:
            return

        convo_dir = self.get_convo_path(self.current_convo)
        meta = self.build_meta_state(convo_id=self.current_convo)
        self.write_convo_file(convo_dir, meta, 'meta')

    def load_injected_file(self, file_path: Path, base_context: Path = None, check_duplicates: bool = False) -> List[Dict[str, Any]]:
        """Load injected files from a text file with # comments and ./ convention.
        
        Args:
            file_path: Path to the injected text file
            base_context: Base context for resolving ./ paths (defaults to current_context)
            check_duplicates: If True, checks against existing injected_files to avoid duplicates
        
        Returns:
            List of injection records with 'file' and 'injected_at' keys
        """
        if not file_path.exists():
            return []
        
        if base_context is None:
            base_context = self.current_context
            
        injected_files = []
        seen = set()
        
        if check_duplicates:
            seen = {inj.get('file') for inj in self.injected_files if isinstance(inj, dict)}
        
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue
                    
                    # Handle different path conventions
                    if line.startswith('./'):
                        # Context-relative: ./main.py
                        full_path = base_context / line[2:]
                        stored_path = str(full_path)
                    elif line.startswith('/'):
                        # Absolute path: /Users/val/project/main.py
                        abs_path = Path(line)
                        if abs_path.exists():
                            stored_path = str(abs_path)
                        else:
                            print(f"Warning: Absolute path {line} does not exist, skipping")
                            continue
                    else:
                        # Relative to current working directory: ideas/cli/main.py
                        full_path = Path.cwd() / line
                        if full_path.exists():
                            stored_path = str(full_path)
                        else:
                            print(f"Warning: Path {line} does not exist, skipping")
                            continue
                    
                    # Check file existence and duplicates
                    if Path(stored_path).exists():
                        if not check_duplicates or stored_path not in seen:
                            injected_files.append({
                                'file': stored_path,
                                'injected_at': datetime.datetime.now().isoformat() + 'Z'
                            })
                            seen.add(stored_path)
        except Exception:
            print(f"Warning: Failed to load injected file from {file_path}")
        
        return injected_files

    def get_injected_files(self) -> List[Dict[str, Any]]:
        """Get all injected files by reading from disk (no caching)."""
        injected_files: List[Dict[str, Any]] = []

        # Auto-inject Makefile
        if self.config.get('auto_inject_makefile', True):
            makefile_path = self.current_context / 'Makefile'
            if makefile_path.exists():
                injected_files.append({
                    'file': str(makefile_path),
                    'injected_at': datetime.datetime.now().isoformat() + 'Z'
                })

        # Auto-injected files from injected.txt
        injected_txt_path = self.current_context / 'injected.txt'
        injected_files.extend(self.load_injected_file(injected_txt_path))
        
        # Manual injections from local.injected.txt
        local_injected_path = self.current_context / 'convos' / 'local.injected.txt'
        manual_injections = self.load_injected_file(local_injected_path, check_duplicates=False)
        injected_files.extend(manual_injections)
        
        return injected_files

    def save_injected_file(self, file_path: Path, injections: List[str], header: str = None, mode: str = 'write') -> bool:
        """Save injections to a text file with proper formatting.
        
        Args:
            file_path: Path to the injected text file
            injections: List of file paths to inject
            header: Optional header comment to include
            mode: 'write' to overwrite, 'append' to append
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.ensure_dir(file_path.parent)
            
            if mode == 'append':
                with open(file_path, 'a') as f:
                    if header and not file_path.exists():
                        f.write(f"{header}\n")
                    for injection in injections:
                        f.write(f"{injection}\n")
            else:  # write mode
                with open(file_path, 'w') as f:
                    if header:
                        f.write(f"{header}\n")
                    for injection in injections:
                        f.write(f"{injection}\n")
            return True
        except Exception:
            print(f"Warning: Failed to save injected file to {file_path}")
            return False
    
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
        self.save_user_state()
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

    def get_pending_user_message(self) -> Optional[str]:
        if not self.current_convo:
            return None

        history = self.load_convo_history()
        if not history:
            return None

        last = history[-1]
        if not isinstance(last, dict):
            return None

        if last.get('role') != 'user':
            return None

        content = last.get('content')
        if not isinstance(content, str):
            return None

        return content
    
    def send_message(self, message: str) -> str:
        """Send a message to the AI and get response."""
        if not self.current_convo:
            self.create_convo()
        
        convo_dir = self.get_convo_path(self.current_convo)

        pending_message = self.retry_message
        retry_this_turn = bool(pending_message is not None and pending_message == message)
        self.retry_message = ''
        
        if not retry_this_turn:
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
        if not retry_this_turn:
            messages.append({'role': 'user', 'content': message})
        
        # Get AI response with tool calling
        try:
            # Get available tools
            tools = self.get_available_tools()
            print(f"DEBUG: Sending {len(tools)} tools to AI:")
            for i, tool in enumerate(tools):
                print(f"DEBUG: Tool {i}: {tool.get('function', {}).get('name', 'unknown')}")
            
            response = self.client.chat.completions.create(
                model=self.current_model,
                messages=messages,
                tools=tools,
                tool_choice="auto" if tools else None,
                temperature=0.7
            )
            
            # Handle tool calls
            if response.choices[0].message.tool_calls:
                print(f"DEBUG: AI made {len(response.choices[0].message.tool_calls)} tool calls:")
                for i, tool_call in enumerate(response.choices[0].message.tool_calls):
                    print(f"DEBUG: Tool call {i}: {tool_call.function.name} with args: {tool_call.function.arguments}")
                ai_response = self.handle_tool_calls(response, messages, convo_dir)
            else:
                print("DEBUG: AI did not make any tool calls")
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
    
    def dispatch_command(self, line: str) -> bool:
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
                self.save_user_state()
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
    
    def handle_switch(self, args: List[str]):
        """Handle context switching."""
        if not args:
            # List available contexts (subdirectories of current directory)
            print("Available contexts:")
            for item in Path.cwd().iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    marker = " (current)" if item == self.current_context else ""
                    print(f"  {item.name}{marker}")
            return
        
        if args[0] == 'list':
            self.handle_switch([])
            return
        
        # Switch to specific context
        old_convo = self.current_convo
        old_context_rel = str(self.current_context)

        new_context = Path.cwd() / args[0]
        if new_context.exists() and new_context.is_dir():
            old_context = self.set_current_context(new_context)  # Centralized chdir
            
            self.load_context_state()  # Load context after changing directory

            new_convo = self.current_convo
            new_context_rel = str(self.current_context)

            if old_convo:
                leave_meta: Dict[str, Any] = {
                    'timestamp': datetime.datetime.now().isoformat() + 'Z',
                    'event': 'switch_context',
                    'from_context': str(old_context),
                    'to_context': new_context_rel,
                    'to_convo': new_convo,
                }
                old_convo_dir = self.get_convo_path(old_convo)
                self.write_convo_file(old_convo_dir, leave_meta, 'meta')
            print(f"Switched to context: {new_context}")
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
        """Handle file injection using local.injected.txt."""
        local_injected_path = self.current_context / 'convos' / 'local.injected.txt'
        
        if not args:
            print("Currently injected files:")
            for injected in self.get_injected_files():
                print(f"  {injected['file']}")
            return
        
        if args[0] == 'list':
            self.handle_inject([])
        elif args[0] == 'clear':
            # Clear the local.injected.txt file using shared save function
            header = "# Local injected files for this context\n# Add files to inject, comment out with # to disable\n"
            if self.save_injected_file(local_injected_path, [], header=header, mode='write'):
                self.write_meta_update()
                print("Cleared injected files")
            else:
                print(f"Warning: Failed to clear {local_injected_path}")
        elif args[0] == 'drop':
            if len(args) < 2:
                print("Usage: /inject drop <file>")
                return
            file_path = args[1]
            
            # Remove from local.injected.txt using shared save function
            try:
                # Read existing lines and filter out the target file
                existing_injections = self.load_injected_file(local_injected_path, base_context=self.current_context, check_duplicates=False)
                filtered_injections = [inj['file'] for inj in existing_injections if inj['file'] != file_path]
                
                # Also read raw lines to preserve comments and formatting
                raw_lines = []
                if local_injected_path.exists():
                    with open(local_injected_path, 'r') as f:
                        raw_lines = f.readlines()
                
                # Filter raw lines, preserving comments
                filtered_lines = []
                for line in raw_lines:
                    stripped = line.strip()
                    if stripped != file_path and not stripped.startswith('# ' + file_path):
                        filtered_lines.append(line)
                
                # Write back the filtered content
                with open(local_injected_path, 'w') as f:
                    f.writelines(filtered_lines)
                
                self.write_meta_update()
                print(f"Dropped injected file: {file_path}")
            except Exception:
                print(f"Warning: Failed to drop {file_path} from {local_injected_path}")
        else:
            # Inject specific file
            file_path = args[0]
            
            # Support both lab-root-relative and current-context-relative paths
            if file_path.startswith('./'):
                # Current context relative (./main.py)
                full_path = self.current_context / file_path[2:]
                stored_path = str(full_path)
            else:
                # Relative to current working directory (ideas/cli/main.py)
                full_path = Path.cwd() / file_path
                stored_path = str(full_path)
                
            if full_path.exists():
                # Append to local.injected.txt using shared save function
                if self.save_injected_file(local_injected_path, [file_path], mode='append'):
                    self.write_meta_update()
                    print(f"Injected file: {stored_path}")
                else:
                    print(f"Warning: Failed to add {stored_path} to {local_injected_path}")
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

    def show_config(self):
        """Show current configuration."""
        print("Current Configuration:")
        print(f"  Model: {self.current_model} ({self.current_endpoint})")
        print(f"  Context: {self.current_context}")
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
        
        injected_files = self.get_injected_files()
        if injected_files:
            print(f"  Injected Files: {len(injected_files)}")
            for injected in injected_files:
                print(f"    - {injected['file']}")
        else:
            print("  Injected Files: None")

    def show_status(self):
        """Show current status."""
        print(f"context: {self.current_context}")
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
        parts.append(f"context: {self.current_context}")
        
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
        
        pending_message = self.get_pending_user_message()
        if pending_message is not None:
            self.retry_message = pending_message
            print("Pending user message detected; press Enter to retry or edit before sending")
        else:
            self.retry_message = ''
        
        while True:
            try:
                # Show status
                status = self.get_status_line()
                print(f"\n{status}")
                
                # Get input
                line = self.session.prompt(">>> ", default=self.retry_message).strip()

                if not line:
                    continue

                self.append_history_line(line)

                if line.startswith('!'):
                    cmd = line[1:].strip()
                    if not cmd:
                        continue
                    try:
                        proc = subprocess.run(
                            cmd,
                            shell=True,
                            text=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                        )
                        if proc.stdout:
                            print(proc.stdout.rstrip('\n'))
                        if proc.returncode != 0:
                            print(f"(exit {proc.returncode})")
                    except Exception as e:
                        print(f"Shell error: {e}")
                    continue
                
                # Handle commands
                if self.dispatch_command(line):
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

    def get_available_tools(self) -> List[Dict]:
        """Get available tools from tool index."""
        tools = []
        
        # Import shell module to get tool signature
        try:
            from .tools import shell as shell_module
            print(f"DEBUG: shell module imported successfully")
            if hasattr(shell_module, 'shell') and hasattr(shell_module.shell, 'tool_signature'):
                print(f"DEBUG: shell.tool_signature found: {shell_module.shell.tool_signature}")
                tools.append(shell_module.shell.tool_signature)
            else:
                print(f"DEBUG: shell.tool_signature not found")
                print(f"DEBUG: shell function exists: {hasattr(shell_module, 'shell')}")
                if hasattr(shell_module, 'shell'):
                    print(f"DEBUG: shell function attributes: {dir(shell_module.shell)}")
        except ImportError as e:
            print(f"DEBUG: Failed to import shell module: {e}")
        
        print(f"DEBUG: Total tools loaded: {len(tools)}")
        return tools
    
    def execute_tool_call(self, tool_call) -> Dict[str, Any]:
        """Execute a tool call using the tool index."""
        function_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)
        
        # Look up function in tool_index
        if function_name in tool_index:
            try:
                result = tool_index[function_name](**arguments)
                return {"result": result, "success": True}
            except Exception as e:
                return {"error": str(e), "success": False}
        else:
            return {"error": f"Unknown tool: {function_name}", "success": False}
    
    def handle_tool_calls(self, response, messages, convo_dir) -> str:
        """Handle tool calls and continue conversation."""
        tool_results = []
        
        # Execute each tool call
        for tool_call in response.choices[0].message.tool_calls:
            result = self.execute_tool_call(tool_call)
            tool_results.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.function.name,
                "content": json.dumps(result)
            })
        
        # Add AI's tool call request to messages
        messages.append(response.choices[0].message)
        
        # Add tool results to messages
        messages.extend(tool_results)
        
        # Get final AI response
        try:
            final_response = self.client.chat.completions.create(
                model=self.current_model,
                messages=messages,
                temperature=0.7
            )
            ai_response = final_response.choices[0].message.content
        except Exception as e:
            ai_response = f"Error after tool execution: {str(e)}"
        
        # Write tool interaction to conversation
        tool_msg = [{
            'role': 'asst',
            'content': ai_response,
            'timestamp': datetime.datetime.now().isoformat() + 'Z',
            'tool_calls': [
                {
                    'name': tc.function.name,
                    'arguments': tc.function.arguments,
                    'result': json.loads(tr['content'])
                }
                for tc, tr in zip(response.choices[0].message.tool_calls, tool_results)
            ]
        }]
        self.write_convo_file(convo_dir, tool_msg, 'asst')
        
        return ai_response

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
