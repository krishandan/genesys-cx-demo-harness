"""HTTP Basic auth for /admin.

Deliberately not the gx X-API-Key. The API-key middleware skips /admin entirely, and
this dependency is the only thing that opens it, so neither credential grants the
other's surface.
"""

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import get_settings

ADMIN_PREFIX = "/admin"

_basic = HTTPBasic(realm="Backlot admin")


def require_admin(
    credentials: Annotated[HTTPBasicCredentials, Depends(_basic)],
) -> str:
    settings = get_settings()

    # compare_digest on both halves, and never short-circuit on the username, so a
    # wrong user and a wrong password are indistinguishable in timing.
    user_ok = hmac.compare_digest(credentials.username, settings.admin_user)
    password_ok = hmac.compare_digest(credentials.password, settings.admin_password)

    if not (user_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": 'Basic realm="Backlot admin"'},
        )
    return credentials.username


AdminUser = Annotated[str, Depends(require_admin)]
