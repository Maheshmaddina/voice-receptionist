"""Retell webhook signature verification.

Enabled when RETELL_API_KEY is set (production). Skipped otherwise so local dev,
tests, and the text-mode eval harness can hit the tools directly.
"""

import os

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RetellSignatureMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        api_key = os.environ.get("RETELL_API_KEY")
        verify = os.environ.get("VERIFY_RETELL_SIGNATURE", "").lower() == "true"
        if verify and api_key and request.url.path.startswith("/tools/"):
            from retell import Retell

            body = await request.body()
            signature = request.headers.get("x-retell-signature", "")
            if not Retell.verify(body.decode(), api_key=api_key, signature=signature):
                return JSONResponse({"error": "invalid signature"}, status_code=401)
        return await call_next(request)
