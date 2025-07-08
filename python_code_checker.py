import re
import ast
from pydantic import BaseModel, Field, field_validator

# ANSI escape code removal
ANSI_ESCAPE = re.compile(r'\x1b\[.*?m')
def _strip_ansi(text):
    return ANSI_ESCAPE.sub('', text)

class PythonCode(BaseModel):
    """
    Jupyter code cell content structure with selective restrictions:
    - Magic commands: Only allowed if in whitelist
    - Shell commands (!): All blocked
    - Python functions: All allowed except input()
    """
    content: str = Field(..., description='Jupyter Python Code')
    
    @field_validator('content')
    @classmethod
    def validate_code_syntax(cls, code_str):
        lines = code_str.splitlines()
        
        # Allowed magic commands list
        allowed_magics = [
            # Line magic commands (% prefix)
            '%matplotlib', '%pylab', '%numpy', '%pandas', '%timeit', '%time',
            '%who', '%whos', '%pwd', '%cd', '%ls', '%run', '%load',
            '%env', '%config', '%pinfo', '%pdef', '%psource', '%pfile',
            '%reset', '%hist', '%history', '%store', '%alias',
            
            # Cell magic commands (%% prefix)
            '%%time', '%%timeit', '%%writefile', '%%capture', '%%latex',
            '%%html', '%%javascript', '%%markdown', '%%python'
        ]
        
        # Check for shell commands (!)
        for line in lines:
            line_stripped = line.strip()
            
            # Check for shell commands
            if line_stripped.startswith('!'):
                raise ValueError(f"Shell commands are not allowed: {line_stripped}")
        
        # Check magic commands (whitelist approach)
        for line in lines:
            line_stripped = line.strip()
            
            # Check for magic commands
            if line_stripped.startswith('%') or line_stripped.startswith('%%'):
                # Extract base command (removing options)
                command_parts = line_stripped.split()
                base_command = command_parts[0] if command_parts else line_stripped
                
                if base_command not in allowed_magics:
                    allowed_list = ", ".join(allowed_magics)
                    raise ValueError(f"Magic command not allowed: {base_command}. Only these magic commands are allowed: {allowed_list}")
        
        # Exclude magic commands from Python code analysis
        python_lines = [line for line in lines if not (
            line.strip().startswith('%') or 
            line.strip().startswith('%%') or
            line.strip().startswith('!'))]
        
        # If there's no Python code (only magic commands)
        if not python_lines:
            return code_str
            
        # Parse Python code and check for forbidden functions (input)
        python_code = '\n'.join(python_lines)
        try:
            tree = ast.parse(python_code)
            cls._check_forbidden_functions(tree)
        except SyntaxError as e:
            raise ValueError(f"Python syntax error: {e}")
        except ValueError as e:
            raise e
            
        return code_str
    
    @classmethod
    def _check_forbidden_functions(cls, tree):
        """
        Traverse the AST to check for forbidden function calls (only input is forbidden)
        """
        for node in ast.walk(tree):
            # Check function calls
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == 'input':
                    raise ValueError("The input() function is not allowed")

def python_code_type_checker(code:str):
    """Python code string validator"""
    PythonCode(content=code)
    
