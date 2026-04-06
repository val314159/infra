
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
