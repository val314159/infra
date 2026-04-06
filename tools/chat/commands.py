import sys
import datetime
from typing import Any

class Commands:
    """Command mix-in"""

    commands = ['/convo', '/switch', '/prompts', '/prompt', '/inject', '/model', '/show', '/help', '/quit']

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
            if not args:
                print("Usage: /show <subcommand>")
                print("  config   - Show current configuration")
                print("  status   - Show current status")
                print("  history  - Show conversation history")
            elif args[0] == 'config':
                self.show_config()
            elif args[0] == 'status':
                self.show_status()
            elif args[0] == 'history':
                self.show_history()
            else:
                print(f"Unknown show subcommand: {args[0]}")
                print("Available: config, status, history")
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
                if not isinstance(getattr(self, 'current_context_state', None), dict):
                    self.current_context_state = {}
                self.current_context_state['last_convo_name'] = convo_name
                self.save_context_state()
                self.save_state()
                print(f"Switched to conversation: {convo_name}")
            else:
                print(f"Conversation '{convo_name}' not found")
    
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
            print(f"Warning: Failed to get relative path for {self.current_context}")
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
                print(f"Warning: Failed to get relative path for {self.current_context}")
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
    
