import os
from typing import Iterable, Optional, Set

import jwt
from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SupabaseAuthMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        exempt_paths: Optional[Iterable[str]] = None,
        exempt_prefixes: Optional[Iterable[str]] = None,
    ):
        super().__init__(app)
        self.exempt_paths: Set[str] = set(exempt_paths or [])
        self.exempt_prefixes: Set[str] = set(exempt_prefixes or [])
        self.jwt_secret = os.getenv("SUPABASE_JWT_SECRET")

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if (
            request.method == "OPTIONS"
            or path in self.exempt_paths
            or any(path.startswith(prefix) for prefix in self.exempt_prefixes)
        ):
            return await call_next(request)

        if not self.jwt_secret:
            raise HTTPException(status_code=500, detail="Auth secret not configured")

        auth_header = request.headers.get("Authorization") or ""
        if not auth_header.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")

        token = auth_header.split(" ", 1)[1].strip()
        if not token:
            raise HTTPException(status_code=401, detail="Missing bearer token")

        try:
            payload = jwt.decode(
                token,
                self.jwt_secret,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid token") from exc

        user_id = payload.get("sub") or payload.get("user_id")
        email = payload.get("email")

        if not user_id:
            raise HTTPException(status_code=401, detail="Token missing user identifier")

        request.state.user_id = user_id
        request.state.email = email
        request.state.token = token
        request.state.jwt_payload = payload
        return await call_next(request)
