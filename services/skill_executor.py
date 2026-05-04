# services/skill_executor.py
"""
KUSMUS Skill Executor — Bridges the API to actual Kushub Python scripts.
Handles dynamic loading of skills from the kushub/ directory.
"""

import os
import importlib.util
import json
import traceback

class SkillExecutor:
    def __init__(self, base_path=None):
        # Default to the kushub/ directory in the project root
        if base_path is None:
            self.base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'kushub', 'skills'))
        else:
            self.base_path = base_path

    def execute_skill(self, skill_id: str, params: dict) -> dict:
        """
        Dynamically load and execute a Python-based skill.
        Expects a file at {base_path}/{skill_id}.py with a 'run' function.
        """
        # Sanitize skill_id to prevent path traversal
        safe_id = "".join([c for c in skill_id if c.isalnum() or c in ('_', '-')])
        skill_file = f"{safe_id}.py"
        file_path = os.path.join(self.base_path, skill_file)

        if not os.path.exists(file_path):
            return {
                "success": False,
                "error": f"Skill source not found at {file_path}",
                "skill_id": skill_id
            }

        try:
            # Load the module dynamically
            spec = importlib.util.spec_from_file_location(safe_id, file_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Every Kushub skill must implement a 'run' function
            if not hasattr(module, 'run'):
                return {
                    "success": False,
                    "error": f"Skill '{skill_id}' does not implement a 'run(params)' function.",
                }

            # Execute the skill
            result_data = module.run(params)
            
            return {
                "success": True,
                "skill_id": skill_id,
                "data": result_data
            }

        except Exception as e:
            print(f"[SkillExecutor] Error running {skill_id}: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc() if os.getenv('FLASK_ENV') == 'development' else None
            }

    def execute_dynamic_code(self, code: str, params: dict = None) -> dict:
        """
        Execute arbitrary Python code provided by the AI.
        This provides a 'Code Interpreter' style environment.
        """
        if params is None:
            params = {}
            
        # Create a restricted but functional execution context
        # In a production environment, this should run in a containerized sandbox (Docker/gVisor)
        exec_globals = {
            "__builtins__": __builtins__,
            "params": params,
            "json": json,
            "os": os,
            # Add common data science libraries if available
            "pd": None,
            "np": None
        }
        
        try:
            import pandas as pd
            exec_globals["pd"] = pd
        except ImportError: pass
        
        try:
            import numpy as np
            exec_globals["np"] = np
        except ImportError: pass

        try:
            # We wrap the code in a function to allow local variable isolation
            # or just execute it directly if it's a script.
            # To capture the result, we expect the code to set a variable 'result'
            # or we can inspect the locals.
            
            local_vars = {}
            exec(code, exec_globals, local_vars)
            
            # If the script defined a 'run' function, execute it
            if 'run' in local_vars and callable(local_vars['run']):
                result_data = local_vars['run'](params)
            else:
                # Otherwise, return whatever variables were created, or a 'result' variable
                result_data = local_vars.get('result', local_vars)

            # Cleanup non-serializable objects from result_data
            serializable_result = {}
            if isinstance(result_data, dict):
                for k, v in result_data.items():
                    try:
                        json.dumps(v)
                        serializable_result[k] = v
                    except (TypeError, OverflowError):
                        serializable_result[k] = str(v)
            else:
                serializable_result = str(result_data)

            return {
                "success": True,
                "data": serializable_result,
                "mode": "dynamic"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc() if os.getenv('FLASK_ENV') == 'development' else None
            }

skill_executor = SkillExecutor()
