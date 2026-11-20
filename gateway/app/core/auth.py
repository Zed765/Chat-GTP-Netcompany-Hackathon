"""Demo sign-in. Tokens are signed, so roles are enforced server-side; swapping
`/api/demo/login` for a real identity provider leaves every other endpoint unchanged."""

from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from gateway.app.core.types import Principal, Role

ALGORITHM = "HS256"

DEMO_USERS: tuple[Principal, ...] = (
    Principal(
        user_id="v.tsioutsias", display_name="Vassilis Tsioutsias", team="Sales", role=Role.EMPLOYEE
    ),
    Principal(user_id="a.bilas", display_name="Apostolos Bilas", team="Security", role=Role.ADMIN),
)

_bearer = HTTPBearer(auto_error=False)


def issue_token(principal: Principal, key: bytes, hours: int) -> str:
    claims = {
        "sub": principal.user_id,
        "name": principal.display_name,
        "team": principal.team,
        "role": principal.role.value,
        "exp": datetime.now(UTC) + timedelta(hours=hours),
    }
    return jwt.encode(claims, key, algorithm=ALGORITHM)


def read_token(token: str, key: bytes) -> Principal:
    claims = jwt.decode(token, key, algorithms=[ALGORITHM])
    return Principal(
        user_id=claims["sub"],
        display_name=claims["name"],
        team=claims["team"],
        role=Role(claims["role"]),
    )


async def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in first")
    try:
        return read_token(credentials.credentials, request.app.state.services.keys.session)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session") from exc


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def require(*roles: Role) -> Callable[[Principal], Coroutine[Any, Any, Principal]]:
    async def check(principal: CurrentPrincipal) -> Principal:
        if principal.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This needs a different role")
        return principal

    return check


Admin = Annotated[Principal, Depends(require(Role.ADMIN))]
