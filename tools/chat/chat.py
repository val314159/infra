import os
import uuid
import datetime
import yaml as pyyaml
from pathlib import Path
from typing import Dict, List, Optional, Any
import openai

class Chat:

    def __init__(self, config_path: str = None):

        self.config = self.load_config(config_path)

        self.lab_root = Path(self.config['lab_root'])
        self.convos_dir = Path(self.config['conversation_store'])
        self.prompts_dir = Path(self.config['prompt_library'])
        self.first_convo: Optional[str] = None

        self.endpoints = self.config['endpoints']

        self.ensure_convo_directories_exist()
        
        # Current state
        self.current_context = self.lab_root
        self.current_convo = None
        self.current_prompts = []
        self.current_model = self.config['default_model']
        self.current_endpoint = self.config['default_endpoint']
        self.injected_files = []
        self.auto_inject_makefile = self.config.get('auto_inject_makefile', True)

        self.restore_last_convo = bool(self.config.get('restore_last_convo', True))
        self.last_injected_set: Optional[set] = None


        self.load_state()
        self.load_context_state()
        self.inject_files()
        self.apply_manual_injections_from_context_state()
        self.last_injected_set = {inj.get('file') for inj in self.injected_files if isinstance(inj, dict)}

        # Setup OpenAI client
        self.setup_openai()

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
        self.create_convo_symlink(convo_id, name)

        if not isinstance(getattr(self, 'current_context_state', None), dict):
            self.current_context_state = {}
        self.current_context_state['last_convo'] = convo_id
        self.current_context_state['last_convo_name'] = name

        self.set_context_convo(convo_id)
        if not self.first_convo:
            self.first_convo = convo_id
        self.save_state()
        return convo_id

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

        if include_title and title is not None:
            payload['title'] = title

        return payload

    def write_meta_update(self):
        if not self.current_convo:
            return

        convo_dir = self.get_convo_path(self.current_convo)
        meta = self.build_meta_state(convo_id=self.current_convo)
        self.write_convo_file(convo_dir, meta, 'meta')

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

    def inject_files(self):
        self.injected_files.extend(self.compute_auto_injected_files())

    def build_context(self) -> str:
        context_parts = []

        for prompt in self.current_prompts:
            context_parts.append(f"=== PROMPT: {prompt['name']} v{prompt['version']} ===")
            context_parts.append(prompt['snapshot'])
            context_parts.append("")

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

        context_parts.append("=== CURRENT CONTEXT ===")
        context_parts.append(f"Directory: {self.current_context.relative_to(self.lab_root)}")
        context_parts.append(f"Conversation: {self.current_convo or 'None'}")
        context_parts.append(f"Model: {self.current_model} ({self.current_endpoint})")
        context_parts.append("")

        return "\n".join(context_parts)

    def send_message(self, message: str) -> str:
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

        full_context = self.build_context()
        history = self.load_convo_history()
        messages = [{'role': 'system', 'content': full_context}]

        for msg in history:
            if msg['role'] in ['user', 'assistant']:
                messages.append({'role': msg['role'], 'content': msg['content']})

        messages.append({'role': 'user', 'content': message})

        try:
            response = self.client.chat.completions.create(
                model=self.current_model,
                messages=messages,
                temperature=0.7
            )
            ai_response = response.choices[0].message.content
        except Exception as e:
            ai_response = f"Error: {str(e)}"

        asst_msg = [{
            'role': 'asst',
            'content': ai_response,
            'timestamp': datetime.datetime.now().isoformat() + 'Z'
        }]
        self.write_convo_file(convo_dir, asst_msg, 'asst')

        return ai_response

    def load_convo_history(self) -> List[Dict]:
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
