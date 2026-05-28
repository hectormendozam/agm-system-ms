from fastapi import Security, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from src.rabbitmq_manager import RabbitMQRpcClient

security = HTTPBearer()

_rpc_client = None


def _normalize_role(value: str) -> str:
    mapping = {
        "administrador": "ADMIN",
        "admin": "ADMIN",
        "docente": "DOCENTE",
        "profesor": "DOCENTE",
        "alumno": "ALUMNO",
        "estudiante": "ALUMNO",
    }
    return mapping.get(value.lower(), value.upper())

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
        allowed_roles = {_normalize_role(role) for role in roles}
        user_role = _normalize_role(str(user.get("rol", "")))
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Acceso denegado. Roles permitidos: {list(roles)}",
            )
        user["rol"] = user_role
        return user
    return dependency