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

import os
import glob
import subprocess

from docopt import docopt
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory

from . import __version__

from .chat import Chat
from .files import Files
from .commands import Commands
from .help import HELP_MESSAGE

class ChatCLI(Chat,Files,Commands):

    def __init__(self, config_path: str = None):
        Chat.__init__(self, config_path)
        
        # Setup history and prompt tooling
        self.setup_history()
        self.setup_completion()

    def setup_history(self):
        """Setup command line history persistence."""
        # History file path
        self.history_file = self.lab_home / '.cli-history'
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
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
    
    def setup_completion(self):
        """Setup prompt-toolkit tab completion."""

        class ChatCompleter(Completer):
            def get_completions(self, document, _complete_event):
                text = document.text_before_cursor
                if text.startswith('/'):
                    for cmd in self.commands:
                        if cmd.startswith(text):
                            yield Completion(cmd, start_position=-len(text))
                    return

                try:
                    path = str(self_outer.current_context)
                    files = glob.glob(os.path.join(path, text + '*'))
                    for file_path in files:
                        if os.path.isfile(file_path):
                            basename = os.path.basename(file_path)
                            yield Completion(basename, start_position=-len(text))
                except Exception:
                    print(f"Warning: Failed to list files in {path}")

        self_outer = self
        self.prompt_completer = ChatCompleter()
        self.session = PromptSession(history=self.prompt_history, completer=self.prompt_completer)
    
    def get_status_line(self) -> str:
        """Generate status line for display."""
        parts = []
        parts.append(f"context: {self.current_context.relative_to(self.lab_root)}")
        
        if self.current_convo:
            convo_name = None
            if isinstance(getattr(self, 'current_context_state', None), dict):
                convo_name = self.current_context_state.get('last_convo_name')
            if isinstance(convo_name, str) and convo_name:
                parts.append(f"convo: {convo_name}")
            else:
                parts.append(f"convo: {self.current_convo[:8]}")
        
        if self.current_prompts:
            prompts_str = ', '.join([f"{p['name']}" for p in self.current_prompts])
            parts.append(f"prompts: {prompts_str}")
        
        parts.append(f"model: {self.current_model}")
        
        return ' | '.join(parts)

    def show_help(self):
        """Show help information."""
        print(HELP_MESSAGE)

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

    def show_status(self):
        """Show current status."""
        print(f"context: {self.current_context.relative_to(self.lab_root)}")
        print(f"convo:   {self.current_convo or 'None'}")
        if self.current_prompts:
            prompts_str = ', '.join([f"{p['name']} v{p['version']}" for p in self.current_prompts])
            print(f"prompts: {prompts_str}")
        print(f"model:   {self.current_model} ({self.current_endpoint})")

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
                line = self.session.prompt(">>> ")

                self.append_history_line(line)

                if not line:
                    continue

                elif line.startswith('!'):
                    cmd = line[1:].strip()
                    if not cmd:
                        continue
                    try:
                        proc = subprocess.run(
                            cmd,
                            shell=True,
                            cwd=str(self.current_context),
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
                
                # Handle commands
                elif self.handle_command(line):
                    continue
                
                else:
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
    args = docopt(__doc__, version='Lab Infra Chat CLI ' + __version__)
    config_path = args.get('--config')
    ChatCLI(config_path).run()

if __name__ == '__main__':
    main()
