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
import sys
import yaml as pyyaml
import glob
import subprocess
from typing import Dict, List, Optional, Any

from docopt import docopt
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory

from . import __version__

from .chat import Chat
from .files import Files
from .commands import Commands

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
        commands = ['/convo', '/switch', '/prompts', '/prompt', '/inject', '/model', '/show', '/help', '/quit']

        class ChatCompleter(Completer):
            def get_completions(self, document, complete_event):
                text = document.text_before_cursor
                if text.startswith('/'):
                    for cmd in commands:
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
        
        if self.get_pending_user_message():
            print("Error: incomplete user turn found in conversation history; fix the convo files and restart")
            sys.exit(1)

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
    args = docopt(__doc__, version=f'Lab Infra Chat CLI {__version__}')
    
    config_path = args.get('--config')
    
    cli = ChatCLI(config_path)
    cli.run()

if __name__ == '__main__':
    main()
