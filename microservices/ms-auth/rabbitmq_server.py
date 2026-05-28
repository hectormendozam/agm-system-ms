import logging
import jwt
import sys
import bcrypt
from rabbitmq_manager import RabbitMQRpcServer
import models
from database import SessionLocal
from settings import ALGORITHM, SECRET_KEY

from main import get_password_hash # Importar desde main para usar exactamente la misma lógica

# Asegurar que los logs salgan a stdout
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("[RabbitMQ-RPC ms-auth]")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def _rol_to_string(rol) -> str:
    if isinstance(rol, models.RolUsuario):
        return rol.value
    return str(rol).upper() # Asegurar uppercase

def _normalize_role(rol: str) -> str:
    # Mapeo flexible para soportar nombres legibles o claves de enum
    mapping = {
        "administrador": "ADMIN",
        "admin": "ADMIN",
        "docente": "DOCENTE",
        "profesor": "DOCENTE",
        "alumno": "ALUMNO",
        "estudiante": "ALUMNO"
    }
    normalized = mapping.get(rol.lower(), rol.upper())
    return normalized

def _to_user_dict(usuario: models.Usuario):
    return {
        "id": usuario.id,
        "email": usuario.email,
        "rol": _rol_to_string(usuario.rol),
    }

class AuthRpcHandlers:
    def _get_user_from_token(self, token: str, db):
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            usuario_id = payload.get("sub")
            if usuario_id is None:
                return None, "Token sin sujeto"

            usuario = db.query(models.Usuario).filter(
                models.Usuario.id == int(usuario_id)
            ).first()
            if usuario is None:
                return None, "Usuario no encontrado"

            return usuario, ""
        except jwt.ExpiredSignatureError:
            return None, "Token expirado"
        except (jwt.InvalidTokenError, ValueError) as e:
            return None, f"Token invalido: {str(e)}"

    def validate_token(self, data):
        token = data.get("token")
        print(f"--> [RPC] Validando token: {token[:20]}...", flush=True)
        db = SessionLocal()
        try:
            usuario, error = self._get_user_from_token(token, db)
            
            if usuario is None:
                print(f"--> [RPC] Validacion fallida: {error}", flush=True)
                return {
                    "valid": False,
                    "error_message": error,
                }

            print(f"--> [RPC] Validacion exitosa: {usuario.email}", flush=True)
            return {
                "valid": True,
                "user": _to_user_dict(usuario),
                "error_message": "",
            }

        finally:
            db.close()

    def get_user_by_id(self, data):
        user_id = data.get("user_id")
        db = SessionLocal()
        try:
            usuario = db.query(models.Usuario).filter(
                models.Usuario.id == user_id
            ).first()
            if usuario is None:
                return {
                    "found": False,
                    "error_message": "Usuario no encontrado",
                }

            return {
                "found": True,
                "user": _to_user_dict(usuario),
                "error_message": "",
            }
        finally:
            db.close()

    def check_role(self, data):
        token = data.get("token")
        required_role = data.get("required_role")
        
        if not required_role:
            return {
                "allowed": False,
                "error_message": "required_role es requerido",
            }

        db = SessionLocal()
        try:
            usuario, error = self._get_user_from_token(token, db)
            if usuario is None:
                return {
                    "allowed": False,
                    "error_message": error,
                }

            norm_role = _normalize_role(required_role)
            allowed = _rol_to_string(usuario.rol) == norm_role

            return {
                "allowed": allowed,
                "user": _to_user_dict(usuario),
                "error_message": "" if allowed else "Rol no autorizado",
            }
        finally:
            db.close()

    def create_user(self, data):
        email = data.get("email")
        password = data.get("password")
        rol = data.get("rol", "ALUMNO")
        
        db = SessionLocal()
        try:
            db_user = db.query(models.Usuario).filter(models.Usuario.email == email).first()
            if db_user:
                return {
                    "success": False,
                    "error_message": "Este correo ya esta registrado",
                }

            nuevo_usuario = models.Usuario(
                email=email,
                password_hash=get_password_hash(password),
                rol=_normalize_role(rol),
            )

            db.add(nuevo_usuario)
            db.commit()
            db.refresh(nuevo_usuario)

            return {
                "success": True,
                "user": _to_user_dict(nuevo_usuario),
            }
        except Exception as e:
            db.rollback()
            return {
                "success": False,
                "error_message": str(e),
            }
        finally:
            db.close()

def serve():
    handlers = AuthRpcHandlers()
    server = RabbitMQRpcServer(queue_name='rpc_auth_queue')
    server.register_action('validate_token', handlers.validate_token)
    server.register_action('get_user_by_id', handlers.get_user_by_id)
    server.register_action('check_role', handlers.check_role)
    server.register_action('create_user', handlers.create_user)
    print("--> [RPC] Servidor Auth iniciado en rpc_auth_queue", flush=True)
    server.start()

if __name__ == "__main__":
    serve()
    print("--> [RPC] Servidor Auth iniciado en rpc_auth_queue", flush=True)
    server.start()

if __name__ == "__main__":
    serve()
