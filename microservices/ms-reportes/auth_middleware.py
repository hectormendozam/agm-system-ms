import os
import sys

# Asegurar que el directorio raíz del microservicio esté en el path de búsqueda de Python
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from fastapi import Security, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from rabbitmq_manager import RabbitMQRpcClient

security = HTTPBearer()

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


def get_current_user_rpc(credentials: HTTPAuthorizationCredentials = Security(security)):
    """
    Extrae el token y pregunta a ms-auth por RabbitMQ si es válido.
    """
    token = credentials.credentials
    try:
        rpc_client = RabbitMQRpcClient()
        # Llamada RPC síncrona por software, asíncrona por red
        response = rpc_client.call(
            queue_name='rpc_auth_queue',
            action='validate_token',
            data={'token': token}
        )

        if response and response.get('valid') is True:
            user = response.get('user', {})
            # Retorna el diccionario con {'user_id': 1, 'rol': 'docente', ...}
            return {
                'user_id': user.get('id'),
                'rol': user.get('rol'),
                'email': user.get('email')
            }
        else:
            raise HTTPException(status_code=401, detail="Token inválido o expirado")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el bus de eventos: {str(e)}")

def require_roles(*roles: str):
    """Devuelve una dependencia que valida el token vía RPC y exige uno de los roles dados."""
    def dependency(user_data: dict = Depends(get_current_user_rpc)) -> dict:
        allowed = {_normalize_role(r) for r in roles}
        if _normalize_role(str(user_data.get("rol", ""))) not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Acceso denegado. Roles permitidos: {list(roles)}",
            )
        return user_data
    return dependency
