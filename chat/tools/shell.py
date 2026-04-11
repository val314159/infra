import subprocess as _subp
from pathlib import Path as _Path

def shell(cmd):
    """Execute shell command in Docker container and return structured result for tool calling."""    
    try:
        result = _subp.run(
            ["docker", "exec", "-it", "-w", _Path.cwd(),
             "sandbox", "sh", "-c", cmd],
            capture_output=True, 
            text=True,  
            timeout=30,  # Prevent hanging
        )        
        # Return structured result for OpenAI
        return {
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except _subp.TimeoutExpired:
        return {
            "success": False,
            "error": "Command timed out after 30 seconds",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }
shell.tool_signature = {
    "type": "function",
    "function": {
        "name": "shell",
        "description": "Execute shell commands in a Docker container (sandbox) using sh and return structured results with success status, stdout, stderr, and exit code. Supports shell variables, pipes, and standard POSIX shell features.",
        "parameters": {
            "type": "object",
            "properties": {
                "cmd": {
                    "type": "string",
                    "description": "Shell command to execute in the Docker container"
                }
            },
            "required": ["cmd"]
        }
    }
}
