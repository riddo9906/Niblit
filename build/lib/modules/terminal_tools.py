import shlex
import subprocess

class TerminalTools:
    def run(self, cmd, timeout=10):
        try:
            # Split into argument list to avoid shell injection; never use shell=True
            args = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
            result = subprocess.check_output(  # noqa: S603
                args, shell=False, stderr=subprocess.STDOUT, timeout=timeout
            )
            return result.decode(errors='replace')
        except FileNotFoundError as e:
            return f"Command not found: {e}"
        except subprocess.TimeoutExpired:
            return "Error: command timed out"
        except Exception as e:
            return f"Error running command: {e}"

    def write_file(self, path, content):
        try:
            with open(path,'w',encoding='utf-8') as f:
                f.write(content)
            return f"Wrote to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

    def read_file(self, path):
        try:
            with open(path,'r',encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {e}"
if __name__ == "__main__":
    print('Running terminal_tools.py')
