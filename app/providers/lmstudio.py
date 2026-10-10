"""
LM Studio provider — OpenAI-compatible local API.

Communicates with LM Studio running at http://localhost:1234/v1
(or any configured URL). Uses the openai SDK for transport.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from openai import OpenAI

from app.core.config import LMStudioSettings
from app.core.logging import get_logger
from app.providers.base import LLMProvider

logger = get_logger("providers.lmstudio")


class LMStudioProvider(LLMProvider):
    """
    LLM provider that talks to LM Studio via its OpenAI-compatible REST API.

    Configuration is loaded from LMStudioSettings (env vars or config/app.yaml).
    The model can be overridden at construction time via the `model` argument
    (maps to the --model CLI flag).
    """

    def __init__(
        self,
        settings: Optional[LMStudioSettings] = None,
        model: Optional[str] = None,
    ) -> None:
        self.settings = settings or LMStudioSettings()
        self.model = model or self.settings.model

        self._client = OpenAI(
            base_url=self.settings.base_url,
            api_key=self.settings.api_key,
            timeout=float(self.settings.timeout_seconds),
            max_retries=0,  # We implement our own retry logic
        )
        logger.debug(
            "LMStudioProvider initialised: base_url=%s model=%s",
            self.settings.base_url,
            self.model,
        )

    # ── Public interface ──────────────────────────────────────────────────────

    def health_check(self) -> bool:
        """Ping LM Studio and verify the configured model is loaded."""
        try:
            models = self._client.models.list()
            model_ids = [m.id for m in models.data]
            logger.debug("LM Studio models available: %s", model_ids)
            if not model_ids:
                logger.warning("LM Studio is reachable but no models are loaded.")
                return False
            if self.model not in model_ids:
                logger.warning(
                    "Configured model '%s' not found in LM Studio. "
                    "Available: %s",
                    self.model,
                    model_ids,
                )
                # Still return True — LM Studio may auto-load or user may switch
            return True
        except Exception as exc:
            logger.error("LM Studio health check failed: %s", exc)
            return False

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Generate free-form text from the LLM.

        Retries up to settings.max_retries times on transient errors.
        """
        messages = self._build_messages(prompt, system_prompt)
        return self._call_with_retry(messages, expect_json=False)

    def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        schema: Optional[dict] = None,
    ) -> dict:
        """
        Generate a structured JSON response from the LLM.

        Appends a strong JSON instruction to the system prompt if not already
        present, and attempts to parse + repair the output.

        Raises:
            ValueError: If valid JSON cannot be extracted after all retries.
        """
        json_system = self._build_json_system_prompt(system_prompt, schema)
        messages = self._build_messages(prompt, json_system)

        raw = self._call_with_retry(messages, expect_json=True)
        return self._parse_json(raw)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_messages(
        self,
        prompt: str,
        system_prompt: Optional[str],
    ) -> list[dict]:
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _build_json_system_prompt(
        self,
        system_prompt: Optional[str],
        schema: Optional[dict],
    ) -> str:
        base = system_prompt or ""
        instruction = (
            "\n\nYou MUST respond with valid JSON only. "
            "Do NOT include any preamble, thinking process, or <think> tags. "
            "Do NOT include any text before or after the JSON object. "
            "Do NOT use markdown code fences. "
            "Output only the raw JSON object."
        )
        if schema:
            schema_str = json.dumps(schema, indent=2)
            instruction += f"\n\nThe JSON must conform to this schema:\n{schema_str}"
        return base + instruction

    def _call_with_retry(
        self,
        messages: list[dict],
        expect_json: bool = False,
    ) -> str:
        last_error: Optional[Exception] = None

        for attempt in range(1, self.settings.max_retries + 1):
            try:
                logger.debug(
                    "LLM call attempt %d/%d (model=%s)",
                    attempt,
                    self.settings.max_retries,
                    self.model,
                )
                t0 = time.monotonic()
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": self.settings.max_tokens,
                    "temperature": self.settings.temperature,
                }
                if expect_json:
                    kwargs["response_format"] = {"type": "json_object"}

                try:
                    response = self._client.chat.completions.create(**kwargs)
                except Exception as json_mode_err:
                    # If model doesn't support json_object mode, retry without response_format
                    if "response_format" in kwargs:
                        logger.debug("json_object format not supported by backend, retrying without it: %s", json_mode_err)
                        del kwargs["response_format"]
                        response = self._client.chat.completions.create(**kwargs)
                    else:
                        raise json_mode_err

                elapsed = time.monotonic() - t0
                content = response.choices[0].message.content or ""
                logger.debug(
                    "LLM responded in %.1fs, %d chars",
                    elapsed,
                    len(content),
                )
                return content

            except Exception as exc:
                last_error = exc
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s",
                    attempt,
                    self.settings.max_retries,
                    exc,
                )
                if attempt < self.settings.max_retries:
                    time.sleep(2 ** attempt)  # Exponential back-off

        raise RuntimeError(
            f"LM Studio call failed after {self.settings.max_retries} attempts. "
            f"Last error: {last_error}"
        )

    def _parse_json(self, raw: str) -> dict:
        """
        Extract and parse JSON from the LLM response.

        Strategy:
        1. Strip <think>...</think> reasoning blocks.
        2. Clean code fences (both closed and unclosed).
        3. Try direct parse.
        4. Try extracting the outer {...} block.
        5. Attempt auto-repair on truncated JSON (missing closing braces/brackets).
        """
        # Strip thinking tags from reasoning models
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()

        # Strip markdown fences if present
        # Handles ```json ... ``` or unclosed ```json ...
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            cleaned = cleaned.strip()

        # 1. Direct parse
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 2. Extract balanced outer {...} block
        start_idx = cleaned.find("{")
        end_idx = cleaned.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            candidate = cleaned[start_idx : end_idx + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        # 3. Handle unclosed/truncated JSON by attempting to close open brackets/braces
        if start_idx != -1:
            candidate = cleaned[start_idx:]
            # Count unclosed brackets
            open_braces = candidate.count("{") - candidate.count("}")
            open_brackets = candidate.count("[") - candidate.count("]")
            # Remove any trailing incomplete string or comma
            trimmed = candidate.rstrip().rstrip(",")
            if trimmed.count('"') % 2 != 0:
                trimmed += '"'
            repaired = trimmed + ("]" * max(0, open_brackets)) + ("}" * max(0, open_braces))
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass

        raise ValueError(
            f"LLM response is not valid JSON.\n"
            f"Raw response (first 500 chars):\n{raw[:500]}"
        )
