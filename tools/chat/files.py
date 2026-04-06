import os
import yaml as pyyaml
import json
import datetime
from pathlib import Path
from typing import Dict, Optional

class Files:
    # Unix permission constants (core architectural choices)
    PERM_IMMUTABLE = 0o444  # read-only for all
    PERM_MUTABLE = 0o644    # read-write for owner, read-only for others
    PERM_DIRECTORY = 0o755  # read/write/execute for owner, read/execute for others

    @property
    def lab_home(self) -> Path:
        return Path.home() / '.lab'

    def ensure_convo_directories_exist(self):
        # Ensure directories exist
        self.convos_dir.mkdir(parents=True, exist_ok=True)
        
    def get_context_convos_dir(self, context: Optional[Path] = None) -> Path:
        ctx = context or self.current_context
        return ctx / 'convos'

    def get_context_state_file(self, context: Optional[Path] = None) -> Path:
        return self.get_context_convos_dir(context) / 'context_state.json'

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

    def write_convo_meta(self, convo_id: str, meta: Dict[str, Any]):
        convo_dir = self.get_convo_path(convo_id)
        self.write_convo_file(convo_dir, meta, 'meta')
    
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
