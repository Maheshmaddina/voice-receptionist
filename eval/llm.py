"""Shared LLM client for the eval harness (Layer 2).

Uses any OpenAI-compatible API so graders can re-run with whatever key they
have. Resolution order:

  1. EVAL_API_KEY + EVAL_API_BASE + EVAL_MODEL   (fully explicit)
  2. GEMINI_API_KEY   -> Gemini OpenAI-compat endpoint, gemini-2.5-flash (free tier)
  3. OPENAI_API_KEY   -> api.openai.com, gpt-4.1-mini
"""

from __future__ import annotations

import os

from openai import OpenAI

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"


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
