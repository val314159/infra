
def shell(cmd):
    import subprocess
    print(f"Executing: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(f"Exit code: {result.returncode}")
    print(f"Output: {result.stdout}")
    return result.stdout
