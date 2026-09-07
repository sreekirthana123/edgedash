import sys
import time
import json
import os
import re
from collections import deque
from typing import Any
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from edgedash.runtime import get_runtime_value

try:
    from google import genai
    from google.genai import types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False


class LLMError(Exception):
    """Raised when LLM requests, validation, or retries fail."""
    pass


class RateLimiter:
    def __init__(self):
        self.last_call_time = 0.0
        self.call_timestamps = deque(maxlen=15)

    def wait_if_needed(self):
        now = time.time()
        elapsed = now - self.last_call_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
            now = time.time()

        if len(self.call_timestamps) == 15:
            oldest_call = self.call_timestamps[0]
            if now - oldest_call < 60.0:
                time.sleep(60.0 - (now - oldest_call))
                now = time.time()

        self.last_call_time = now
        self.call_timestamps.append(now)


_limiter = RateLimiter()


def _strip_markdown_fences(text: str) -> str:
    text = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    text = text.strip()
        
    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx != -1 and end_idx != -1:
        text = text[start_idx : end_idx + 1]
    return text


def _validate_schema(data: dict, schema: dict) -> None:
    for key, expected_type in schema.items():
        if key not in data:
            raise ValueError(f"Missing required schema key: '{key}'")
        if expected_type == "string" and not isinstance(data[key], str):
            raise ValueError(f"Key '{key}' must be a string")
        if expected_type == "string|null" and data[key] is not None and not isinstance(data[key], str):
            raise ValueError(f"Key '{key}' must be a string or null")
        if expected_type == "object" and not isinstance(data[key], dict):
            raise ValueError(f"Key '{key}' must be an object")


class GeminiProvider:
    def execute(self, prompt: str, model_name: str, timeout: int = 30) -> str:
        # Automatically pulled from your saved .env variables
        api_key = get_runtime_value("GEMINI_API_KEY")
        if not api_key:
            raise LLMError("LLM check failed: GEMINI_API_KEY environment variable not set. Add it to .env")
        
        if not HAS_GEMINI:
            raise LLMError("google-genai is not installed. Run: pip install google-genai")

        def _call_gemini():
            # Instructor approach: Instantiate modern Client object
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            return response.text

        try:
            # Execute with timeout using ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_call_gemini)
                return future.result(timeout=timeout)
        except FuturesTimeoutError:
            raise LLMError(f"Gemini API timeout after {timeout}s (request may still be processing)")
        except Exception as e:
            raise LLMError(f"Gemini API error: {e}")


_PROVIDERS = {
    "gemini": GeminiProvider
}


def complete_json(prompt: str, schema: dict, config: Any, timeout: int = 30) -> dict:
    provider_name = getattr(config, "llm_provider", "gemini").lower()
    model_name = getattr(config, "llm_model", "gemini-3.6-flash")

    provider_instance = _PROVIDERS[provider_name]()
    _limiter.wait_if_needed()
    
    raw_text = provider_instance.execute(prompt, model_name, timeout=timeout)
    clean_text = _strip_markdown_fences(raw_text)
    parsed_data = json.loads(clean_text)
    _validate_schema(parsed_data, schema)
    return parsed_data


if __name__ == "__main__":
    import collections
    
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        print("provider : gemini")
        print("model    : gemini-3.6-flash")
        print("sending test prompt...")
        
        MockConfig = collections.namedtuple("MockConfig", ["llm_provider", "llm_model"])
        cfg = MockConfig(llm_provider="gemini", llm_model="gemini-3.6-flash")
        
        test_prompt = "Return exactly this JSON block structure: {\"status\": \"ok\"}"
        test_schema = {"status": "string"}
        
        try:
            res = complete_json(test_prompt, test_schema, cfg)
            print(f"✓response: {res}")
        except Exception as err:
            print(f"✗ LLM check failed: {err}")
