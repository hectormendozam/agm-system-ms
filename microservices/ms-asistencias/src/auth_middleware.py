import os
from fastapi import Security, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt as pyjwt

security = HTTPBearer()

_SECRET_KEY = os.getenv("SECRET_KEY", "clave_super_secreta_desarrollo_agm")
_ALGORITHM  = os.getenv("JWT_ALGORITHM", "HS256")

_ROLE_MAP = {
    "administrador": "ADMIN",
    "admin":         "ADMIN",
    "docente":       "DOCENTE",
    "profesor":      "DOCENTE",
    "alumno":        "ALUMNO",
    "estudiante":    "ALUMNO",
}

def _normalize_role(value: str) -> str:
    return _ROLE_MAP.get(str(value).lower(), str(value).upper())


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> dict:
    """Valida el Bearer Token localmente usando el mismo SECRET_KEY que ms-auth."""
    token = credentials.credentials
    try:
        payload = pyjwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except pyjwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Token inválido: {exc}")
    return {
        "id":    payload.get("sub"),
        "rol":   _normalize_role(str(payload.get("rol", ""))),
        "email": payload.get("email"),
    }


def require_roles(*roles: str):
    def dependency(
        credentials: HTTPAuthorizationCredentials = Security(security),
    ) -> dict:
        user = get_current_user(credentials)
        allowed    = {_normalize_role(r) for r in roles}
        user_role  = _normalize_role(str(user.get("rol", "")))
        if user_role not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Acceso denegado. Roles permitidos: {list(roles)}",
            )
        user["rol"] = user_role
        return user
    return dependency
