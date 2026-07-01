"""FastAPI dependency injection."""

from __future__ import annotations

from functools import lru_cache

from common.data_access import DataBackend, get_backend


@lru_cache(maxsize=1)
def get_data_backend() -> DataBackend:
    return get_backend()


# USER-CONFIG: Phase 2 auth middleware injection point
# from fastapi import Depends, HTTPException, Security
# from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
#
# security = HTTPBearer()
#
# async def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
#     """Phase 2: JWT token verification — integrate with predict-client-dev auth."""
#     token = credentials.credentials
#     # TODO: validate JWT against predict-client-dev's auth service
#     raise HTTPException(status_code=401, detail="Auth not implemented")
