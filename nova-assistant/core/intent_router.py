"""
Nova Assistant — Intent Router Module
Uses local LLM (Ollama) to parse natural language commands into structured JSON intents,
with a fast Regex-based fallback for simple commands.
"""

import json
import logging
import re
from typing import Dict, Any

import ollama
from ollama import Client

logger = logging.getLogger("nova.intent")


class IntentRouter:
    """
    Parses voice commands into structured JSON intents.
    
    Tries regex parsing first for speed on common commands.
    Falls back to the local LLM if regex fails or the command is complex.
    """

    # Schema definition for the LLM
    INTENT_SCHEMA = {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": [
                    "open_app", 
                    "search_file", 
                    "open_file", 
                    "chrome_search", 
                    "start_work_mode",
                    "sleep",
                    "chat",
                    "unknown"
                ],
                "description": "The type of action the user wants to perform."
            },
            "app": {
                "type": "string",
                "description": "The name of the app to open (e.g. 'chrome', 'cursor'). Only use with 'open_app'."
            },
            "query": {
                "type": "string",
                "description": "The search query. Only use with 'chrome_search' or 'search_file'."
            },
            "filename": {
                "type": "string",
                "description": "The exact name of the file to open. Only use with 'open_file'."
            },
            "workspace": {
                "type": "string",
                "description": "The name of the workspace to start (e.g. 'default', 'study'). Only use with 'start_work_mode'."
            },
            "message": {
                "type": "string",
                "description": "A natural language conversational response to the user. Use with 'chat' or 'unknown'."
            }
        },
        "required": ["intent"]
    }

    SYSTEM_PROMPT = """You are the natural language understanding engine for Nova, a local AI assistant.
Your job is to parse the user's spoken command into a structured JSON intent.
Do not output any conversational text outside the JSON object.

Intents:
- open_app: The user wants to launch an application (e.g. "open notepad", "launch chrome"). Extract the 'app' name.
- chrome_search: The user wants to search the web (e.g. "search google for python docs", "look up the weather"). Extract the 'query'.
- search_file: The user wants to find a file on their computer (e.g. "find my resume", "search for budget spreadsheet"). Extract the 'query'.
- open_file: The user wants to open a specific file (e.g. "open report.pdf"). Extract the 'filename'.
- start_work_mode: The user wants to start a work routine (e.g. "start work mode", "study mode"). Extract the 'workspace' name if specified, otherwise 'default'.
- sleep: The user wants you to stop listening and go back to sleep (e.g. "go to sleep", "sleep nova", "stop listening").
- chat: The user is asking a conversational question or greeting you (e.g. "what time is it", "hello", "how are you"). Generate a brief, friendly 'message' in response.
- unknown: You cannot understand the command or it requests dangerous/unsupported actions (like deleting files or shutting down the PC). Provide a 'message' explaining why.

IMPORTANT: Your output MUST be valid JSON matching the provided schema. Do not wrap it in markdown code blocks.
"""

    def __init__(self, config: dict):
        self._config = config
        llm_cfg = config.get("llm", {})
        
        self._host = llm_cfg.get("base_url", "http://localhost:11434")
        self._model = llm_cfg.get("primary_model", "qwen2.5:3b-instruct")
        self._fallback_model = llm_cfg.get("fallback_model", "qwen2.5:1.5b-instruct")
        
        # Initialize Ollama client
        self._client = Client(host=self._host)
        
        logger.info(f"Intent router initialized using model '{self._model}' at {self._host}")
        
    def preload_model(self):
        """Force load the Ollama model into memory synchronously."""
        try:
            logger.debug(f"Preloading Ollama model '{self._model}'...")
            self._client.chat(
                model=self._model, 
                messages=[{"role": "user", "content": "hi"}], 
                options={"num_predict": 1},
                keep_alive=-1  # Keep in GPU memory indefinitely
            )
            logger.info(f"Ollama model '{self._model}' preloaded into GPU memory")
        except Exception as e:
            logger.warning(f"Failed to preload model: {e}")

    def parse_intent(self, command: str) -> Dict[str, Any]:
        """
        Parse a natural language command into a structured intent.
        
        Args:
            command: The transcribed voice command.
            
        Returns:
            A dictionary containing the parsed intent.
        """
        cmd_clean = command.strip()
        if not cmd_clean:
            return {"intent": "unknown", "message": "I didn't hear a command."}

        # 1. Try fast rule-based parsing first
        intent = self._fallback_regex_parse(cmd_clean)
        if intent:
            logger.info(f"Parsed via Regex: {intent}")
            return intent
            
        # 2. If regex fails, use the LLM
        logger.debug(f"Regex failed, falling back to LLM for: '{cmd_clean}'")
        try:
            return self._llm_parse(cmd_clean)
        except Exception as e:
            logger.error(f"LLM parsing failed: {e}")
            # If everything fails, return a safe fallback
            return {
                "intent": "chat", 
                "message": f"I heard '{cmd_clean}', but I'm having trouble connecting to my language model to understand it right now."
            }

    def _fallback_regex_parse(self, command: str) -> Dict[str, Any]:
        """
        Fast regex parser for simple, unambiguous commands.
        Returns None if the command is too complex.
        """
        cmd_lower = command.lower()
        
        # Open App: "open [app]" or "launch [app]"
        match = re.match(r"^(?:open|launch|start)\s+(?!work mode)(?!work)(?!study)(.+)$", cmd_lower)
        if match:
            # Check if they said "open file X", which we should ignore here
            target = match.group(1).strip()
            if not target.startswith("file"):
                return {"intent": "open_app", "app": target}

        # Web Search: "search for [query]" or "google [query]"
        match = re.match(r"^(?:search for|search|google|look up)\s+(.+)$", cmd_lower)
        if match:
            return {"intent": "chrome_search", "query": match.group(1).strip()}
            
        # File Search: "find file [query]" or "locate [query]"
        match = re.match(r"^(?:find|locate)(?:\s+file)?\s+(.+)$", cmd_lower)
        if match:
            return {"intent": "search_file", "query": match.group(1).strip()}
            
        # Open File: "open file [filename]"
        match = re.match(r"^open file\s+(.+)$", cmd_lower)
        if match:
            return {"intent": "open_file", "filename": match.group(1).strip()}
            
        # Work Mode
        if "work mode" in cmd_lower or "study mode" in cmd_lower:
            workspace = "study" if "study" in cmd_lower else "default"
            return {"intent": "start_work_mode", "workspace": workspace}
            
        # Sleep
        if cmd_lower in ["sleep", "go to sleep", "stop listening", "quit", "exit"]:
            return {"intent": "sleep"}
            
        # Basic Chat / Status
        if cmd_lower in ["hello", "hi", "hey", "wake up", "are you there"]:
            return {"intent": "chat", "message": "I'm here. How can I help?"}
            
        if "time" in cmd_lower:
            import time
            return {"intent": "chat", "message": f"It is currently {time.strftime('%I:%M %p')}."}
            
        return None

    def _llm_parse(self, command: str) -> Dict[str, Any]:
        """Call Ollama to parse the intent using JSON mode."""
        response = self._client.chat(
            model=self._model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": command}
            ],
            format=self.INTENT_SCHEMA,
            options={
                "temperature": 0.1,  # Keep it deterministic
                "num_predict": 128   # Short output limit for speed
            },
            keep_alive=-1  # Keep in GPU memory indefinitely
        )
        
        output_text = response.get("message", {}).get("content", "").strip()
        logger.debug(f"LLM raw output: {output_text}")
        
        try:
            intent = json.loads(output_text)
            
            # Basic validation
            if "intent" not in intent:
                intent["intent"] = "unknown"
                intent["message"] = "The LLM didn't return a valid intent type."
                
            return intent
        except json.JSONDecodeError:
            logger.error(f"LLM returned invalid JSON: {output_text}")
            return {
                "intent": "unknown", 
                "message": "I had trouble parsing the response from my language model."
            }


if __name__ == "__main__":
    # Quick standalone test
    import yaml
    from pathlib import Path
    
    logging.basicConfig(level=logging.DEBUG)
    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
        
    router = IntentRouter(config)
    
    test_commands = [
        "Open the calculator app",
        "Search google for the best python tutorials",
        "Find my financial report spreadsheet",
        "Start my study mode routine",
        "What time is it right now?",
        "Delete all files in my documents folder", # Should map to unknown
    ]
    
    print("\nTesting Intent Router:")
    for cmd in test_commands:
        print(f"\nCommand: '{cmd}'")
        intent = router.parse_intent(cmd)
        print(f"Result: {json.dumps(intent, indent=2)}")
