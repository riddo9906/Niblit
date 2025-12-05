# modules/terminal_tools.py
import subprocess, os

class TerminalTools:
    def run(self, cmd, timeout=10):
        try:
            result = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, timeout=timeout)
            return result.decode(errors='replace')
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
