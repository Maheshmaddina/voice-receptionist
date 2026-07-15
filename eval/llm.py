"""Shared LLM client for the eval harness (Layer 2).

Uses any OpenAI-compatible API so graders can re-run with whatever key they
have. Resolution order:

  1. EVAL_API_KEY + EVAL_API_BASE + EVAL_MODEL   (fully explicit)
  2. GEMINI_API_KEY   -> Gemini OpenAI-compat endpoint, gemini-2.5-flash (free tier)
  3. OPENAI_API_KEY   -> api.openai.com, gpt-4.1-mini
"""

from __future__ import annotations

import os
import re
import sys
import time

from openai import OpenAI, RateLimitError

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"


def completion(client: OpenAI, **kwargs):
    """chat.completions.create with free-tier-friendly 429 backoff."""
    for attempt in range(8):
        try:
            return client.chat.completions.create(**kwargs)
        except RateLimitError as e:
            m = re.search(r"retry.{0,10}?(\d+(?:\.\d+)?)s", str(e), re.I)
            delay = float(m.group(1)) + 1 if m else 15 * (attempt + 1)
            print(f"    (rate-limited, waiting {delay:.0f}s)", file=sys.stderr)
            time.sleep(min(delay, 70))
    raise RuntimeError("LLM rate limit: exhausted retries")


def make_client() -> tuple[OpenAI, str]:
    if os.environ.get("EVAL_API_KEY"):
        base = os.environ.get("EVAL_API_BASE") or None
        model = os.environ.get("EVAL_MODEL", "gpt-4.1-mini")
        return OpenAI(api_key=os.environ["EVAL_API_KEY"], base_url=base), model
    if os.environ.get("GEMINI_API_KEY"):
        model = os.environ.get("EVAL_MODEL", "gemini-2.5-flash")
        return OpenAI(api_key=os.environ["GEMINI_API_KEY"], base_url=GEMINI_BASE), model
    if os.environ.get("OPENAI_API_KEY"):
        model = os.environ.get("EVAL_MODEL", "gpt-4.1-mini")
        return OpenAI(api_key=os.environ["OPENAI_API_KEY"]), model
    raise SystemExit("Set GEMINI_API_KEY (free at aistudio.google.com), OPENAI_API_KEY, "
                     "or EVAL_API_KEY/EVAL_API_BASE/EVAL_MODEL.")
