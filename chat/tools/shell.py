import subprocess as _subp

def shell(cmd):
    """Execute shell command and return structured result for tool calling."""    
    try:
        print("SHELL:", cmd)
        result = _subp.run(
            cmd, 
            shell=True, 
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
            "command": cmd,
        }
    except _subp.TimeoutExpired:
        return {
            "success": False,
            "error": "Command timed out after 30 seconds",
            "command": cmd,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "command": cmd,
        }
shell.tool_signature = {
    "type": "function",
    "function": {
        "name": "shell",
        "description": "Execute shell commands and return structured results with success status, stdout, stderr, and exit code",
        "parameters": {
            "type": "object",
            "properties": {
                "cmd": {
                    "type": "string",
                    "description": "Shell command to execute"
                }
            },
            "required": ["cmd"]
        }
    }
}
