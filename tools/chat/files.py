import os
import uuid
import yaml as pyyaml
import json
import glob
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import openai

class Files:
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

    def __init__(self):
        # Ensure directories exist
        self.convos_dir.mkdir(parents=True, exist_ok=True)
        
    def is_valid_context(self, context_path: Path) -> bool:
        try:
            context_resolved = context_path.resolve()
            lab_root_resolved = self.lab_root.resolve()
        except Exception:
            print(f"Warning: Failed to resolve paths for context validation: {context_path}")
            return False

        if context_resolved == lab_root_resolved:
            return True

        return lab_root_resolved in context_resolved.parents

    def load_state(self):
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
        except FileNotFoundError:
            # do nothing
            return
        except Exception:
            print(f"Warning: Failed to load state file: {self.state_file}")
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
            print(f"Warning: Failed to save state file: {self.state_file}")
            return

    def load_context_state(self):
        context_state_file = self.get_context_state_file()
        
        try:
            with open(context_state_file, 'r') as f:
                state = json.load(f)
        except FileNotFoundError:
            self.current_context_state = {}
            self.current_convo = None
            return
        except Exception:
            print(f"Warning: Failed to load context state file: {context_state_file}")
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
            print(f"Warning: Failed to save context state file: {context_state_file}")
            return

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
                    'key_env': None
                },
                'vllm': {
                    'url': 'http://localhost:8000/v1',
                    'key_env': None
                }
            },
            'lab_root': os.getcwd(),

            'conversation_store': 'infra/convos',
            'prompt_library': 'infra/prompts',
            'auto_inject_makefile': True
        }
        
        lab_root = default_config['lab_root']

        if config_path is None:
            # reasonable default
            config_path = Path(lab_root) / 'infra' / 'config' / 'chat.yaml'

        # Load config file if it exists
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                loaded_config = pyyaml.safe_load(f)
            # Merge with defaults (loaded config takes precedence)
            default_config.update(loaded_config)
        
        return default_config
    
    def setup_openai(self):
        """Setup OpenAI client for current endpoint."""

        endpoint_config = self.endpoints[self.current_endpoint]

        if self.current_endpoint == 'openai':
            api_key = os.getenv(endpoint_config['key_env'])
            if not api_key:
                raise ValueError(f"Missing {endpoint_config['key_env']} environment variable")
            self.client = openai.OpenAI(api_key=api_key, base_url=endpoint_config['url'])
        else:
            # Local endpoint (Ollama)
            self.client = openai.OpenAI(base_url=endpoint_config['url'], api_key='not-needed')
    
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
    
    def write_convo_file(self, convo_dir: Path, content: Any, file_type: str):
        """Write a conversation file and make it immutable."""
        filename = f"{self.get_next_file_number(convo_dir)}-{file_type}.yaml"
        filepath = convo_dir / filename
        
        with open(filepath, 'w') as f:
            pyyaml.dump(content, f, default_flow_style=False)

        # Make immutable
        os.chmod(filepath, self.PERM_IMMUTABLE)

    def build_meta_state(self, *, include_title: bool = False, title: Optional[str] = None, convo_id: Optional[str] = None) -> Dict[str, Any]:
        try:
            context_rel = str(self.current_context.relative_to(self.lab_root))
        except ValueError:
            context_rel = str(self.current_context.resolve())

        injected_yaml_mtime = None
        try:
            injected_yaml_path = self.current_context / 'injected.yaml'
            if injected_yaml_path.exists():
                injected_yaml_mtime = injected_yaml_path.stat().st_mtime
        except Exception:
            print(f"Warning: Failed to get mtime for {injected_yaml_path}")
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

        if self.auto_inject_makefile:
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
                print(f"Warning: Failed to load injected.yaml from {injected_yaml_path}")
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
                print(f"Warning: Failed to get mtime for {injected_yaml_path}")
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
