from fastapi import Security, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from src.rabbitmq_manager import RabbitMQRpcClient

security = HTTPBearer()

_rpc_client = None

_ROLE_MAP = {
    "administrador": "ADMIN",
    "admin": "ADMIN",
    "docente": "DOCENTE",
    "profesor": "DOCENTE",
    "alumno": "ALUMNO",
    "estudiante": "ALUMNO",
}

def _normalize_role(value: str) -> str:
    return _ROLE_MAP.get(str(value).lower(), str(value).upper())


def _get_rpc_client():
    global _rpc_client
    if _rpc_client is None:
        _rpc_client = RabbitMQRpcClient()
    return _rpc_client


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> dict:
    """
    Intercepta el Bearer Token, lo manda a ms-auth por RabbitMQ RPC
    y retorna el dict con id y rol del usuario.
    Úsalo como dependencia: user = Depends(get_current_user)
    """
    token = credentials.credentials

    try:
        client = _get_rpc_client()
        response = client.call(
            queue_name="rpc_auth_queue",
            action="validate_token",
            data={"token": token},
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error comunicándose con ms-auth: {str(e)}",
        )

    if not response or not response.get("valid"):
        raise HTTPException(
            status_code=401,
            detail=response.get("error_message", "Token inválido o expirado"),
        )

    return response.get("user")


def require_roles(*roles: str):
    """
    Dependencia que valida rol además del token.
    Uso: user = Depends(require_roles("Docente", "Administrador"))
    """
    def dependency(
        credentials: HTTPAuthorizationCredentials = Security(security),
    ) -> dict:
        user = get_current_user(credentials)
        allowed = {_normalize_role(r) for r in roles}
        if _normalize_role(str(user.get("rol", ""))) not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Acceso denegado. Roles permitidos: {list(roles)}",
            )
        return user
    return dependency