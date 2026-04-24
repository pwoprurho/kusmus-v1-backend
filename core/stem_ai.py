# core/stem_ai.py
"""
STEM AI Engine (Conversational Gateway)
Handles routing to subject-specific agents and unified code generation.
"""

import json
import re
from core.engine import KusmusAIEngine
from core.physics_ai import PhysicsSubject
from core.maths_ai import MathsSubject
from core.biology_ai import BiologySubject
from core.chemistry_ai import ChemistrySubject

BASE_GENERATION_PROMPT = """
You are a STEM Simulation Architect building structured JSON blueprints. 
You will not write Javascript code. Instead, you will define the environment, entities, and physics rules in a strictly formatted JSON object. 

=== ARCHITECTURAL LAYERS ===
1. **Config**: Define gravity and world settings. (Camera is AUTO-FIT by default).
2. **Entities**: Define objects (spheres, boxes, planes). 
   - Attributes: `id`, `type`, `mass`, `size` or `radius`, `position`, `rotation`, `color` (hex), `label` (optional text), `opacity` (0.0-1.0).
   - INTERACTIVITY: All objects with `mass > 0` are automatically DRAGGABLE by the user.
3. **Constraints**: Define mechanical links between entities.
4. **Vectors**: Visualize quantities like `velocity` or `force` using Arrow overlays.
5. **Reveal**: ALWAYS include a `reveal` object with `title` and `text` explaining the science.

=== SCIENTIFIC FRAMEWORKS & STANDARDS ===
- Physics Engine: Cannon.js concepts apply (Use Constraints for solid mechanics).
- Graphics: Three.js concepts apply.
- Interactive Feedback: Prefer using labels, vectors, and draggable components to create a PhET-like exploratory environment.
- **Electromagnetism**: Use Arrow vectors (`type="force"`) to represent Field lines. Represent charged particles as small spheres colored red/blue.
- **Thermodynamics & Soft Bodies**: Use many small spheres for ideal gas. Use `CANNON.Spring` (via distance constraints) mapped between bodies for soft-body mesh behavior. Color code heat maps (red for hot/fast, blue for cold/slow).
- **Fluid Dynamics**: Approximate using smoothed arrays of small circle spheres interacting with collisions to simulate SPH.

=== STRICT OUTPUT FORMAT ===
Your response MUST be valid, parseable JSON wrapped in a ```json``` block.

{
  "title": "Simulation Title",
  "concept": "Core scientific concept",
  "description": "Detailed explanation",
  "config": {
    "gravity": [0, -9.82, 0]
  },
  "entities": [
    { "id": "ground", "type": "plane", "mass": 0, "size": [20, 20], "position": [0, 0, 0], "color": "0x333333", "label": "Ground" },
    { "id": "bob", "type": "sphere", "mass": 1.0, "radius": 1.0, "position": [0, 5, 0], "color": "0x0072ff", "label": "Interactive Sphere" }
  ],
  "vectors": [
    { "entity": "bob", "type": "velocity", "color": "0x00ff00" }
  ],
  "constraints": [],
  "reveal": {
    "title": "Exploring Motion",
    "text": "This simulation allows you to drag the sphere and observe its velocity vector in real-time."
  }
}
"""

class StemAIEngine:
    def __init__(self):
        self.subjects = {
            "physics": PhysicsSubject,
            "maths": MathsSubject,
            "biology": BiologySubject,
            "chemistry": ChemistrySubject
        }
        self.planning_model = "gemini-2.5-flash"
        self.generation_model = "gemini-2.5-flash"

    def get_subject_logic(self, subject_name: str):
        return self.subjects.get(subject_name, PhysicsSubject)

    def chat_interact(self, message: str, subject_name: str = "physics", context_logs=None) -> dict:
        """
        Phase 1: Chat with user to gather details for a specific subject.
        """
        subject = self.get_subject_logic(subject_name)
        
        engine = KusmusAIEngine(
            system_instruction=subject.PLANNING_PROMPT,
            model_name=self.planning_model
        )
        
        response_text, thought_trace = engine.generate_response(message, context_logs=context_logs)
        
        state = self._parse_state(response_text, subject_name)
        clean_response = re.sub(r'\[STATE:.*?\]', '', response_text).strip()
        
        return {
            "response": clean_response,
            "state": state,
            "thought_trace": thought_trace
        }

    def generate_simulation(self, design_doc: str, subject_name: str = "physics", retries: int = 2) -> dict:
        """
        Phase 2: Generate high-fidelity code based on the subject's specialization.
        """
        subject = self.get_subject_logic(subject_name)
        full_system_prompt = BASE_GENERATION_PROMPT + "\n" + subject.GENERATION_PROMPT_ADDITION
        
        engine = KusmusAIEngine(
            system_instruction=full_system_prompt,
            model_name=self.generation_model
        )
        
        last_error = None
        for attempt in range(retries + 1):
            try:
                response_text, thought_trace = engine.generate_response(
                    f"Generate the full {subject_name.upper()} simulation code for this design: {design_doc}"
                )
                
                result = self._parse_json(response_text)
                if "errors" not in result:
                    result["thought_trace"] = thought_trace
                    result["model_used"] = self.generation_model
                    return result
                
                last_error = result["errors"][0]
            except Exception as e:
                last_error = str(e)
        
        return {"errors": [f"Deep Generation Failed. Last error: {last_error}"]}

    def generate_simulation_stream(self, design_doc: str, subject_name: str = "physics", chat_context: str = ""):
        """
        Stream the high-fidelity code generation for real-time visualization.
        """
        subject = self.get_subject_logic(subject_name)
        full_system_prompt = BASE_GENERATION_PROMPT + "\n" + subject.GENERATION_PROMPT_ADDITION
        
        engine = KusmusAIEngine(
            system_instruction=full_system_prompt,
            model_name=self.generation_model,
            tools=[]
        )
        
        prompt = f"Generate the full {subject_name.upper()} structured JSON blueprint for this design: {design_doc}"
        if chat_context:
            prompt += f"\n\nHere is the recent conversation history for context on exactly what the user wants to change or build:\n{chat_context}"
        
        for chunk in engine.generate_response_stream(prompt):
            yield chunk

    def fix_simulation(self, failed_code: str, error_msg: str, subject_name: str = "physics") -> dict:
        """
        Self-healing loop: Analyze error and re-generate code.
        """
        subject = self.get_subject_logic(subject_name)
        prompt = f"""
        ERROR DETECTED IN SIMULATION CODE:
        {error_msg}

        FAILING CODE:
        {failed_code}

        STRICT INSTRUCTION:
        1. Identify what caused the error (e.g., missing entity ID, invalid number, bad constraint type).
        2. Re-write the JSON blueprint to FIX the error while maintaining the original simulation intent.
        3. Ensure the output is strictly valid JSON format mapping to the STEM Engine JSON schema.
        """
        
        engine = KusmusAIEngine(
            system_instruction=BASE_GENERATION_PROMPT + "\n" + subject.GENERATION_PROMPT_ADDITION,
            model_name=self.generation_model
        )
        
        response_text, thought_trace = engine.generate_response(prompt)
        result = self._parse_json(response_text)
        if "errors" not in result:
            result["thought_trace"] = thought_trace
            result["model_used"] = self.generation_model
        return result

    def _parse_state(self, text: str, default_subject: str) -> dict:
        # Try explicit [STATE: {...}] tag
        match = re.search(r'\[STATE:\s*({.*?})\s*\]', text, re.DOTALL)
        if match:
            try:
                state_str = match.group(1).replace('\n', ' ')
                state = json.loads(state_str)
                if 'subject' not in state: state['subject'] = default_subject
                return state
            except:
                pass
        
        # Fallback: If the response contains a design document pattern, mark as ready
        if 'SIMULATION:' in text or 'OBJECTS:' in text or '"title"' in text:
            # Extract the design from the full response
            return {"subject": default_subject, "ready": True, "design": text}
        
        return {"subject": default_subject, "ready": False}

    def _parse_json(self, text: str) -> dict:
        result = {}
        
        # Try JSON blueprint first (new format)
        json_match = re.search(r'```json\s*({.*?})\s*```', text, flags=re.DOTALL)
        if json_match:
            try:
                metadata = json.loads(json_match.group(1))
                result.update(metadata)
                return result
            except:
                pass
        
        # Try raw JSON (no code fences)
        stripped = text.strip()
        if stripped.startswith('{') and stripped.endswith('}'):
            try:
                metadata = json.loads(stripped)
                result.update(metadata)
                return result
            except:
                pass
        
        # Legacy: Try old JS code format
        code_match = re.search(r'```(?:javascript|js)\s*(.*?)\s*```', text, flags=re.DOTALL)
        if code_match:
            result["threejs_code"] = code_match.group(1).strip()
            return result
        
        return {"errors": ["Could not parse code or metadata from response"]}
