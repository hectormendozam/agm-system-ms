import logging
import os
import sys

# Añadir el directorio raíz al path para importar rabbitmq_manager
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rabbitmq_manager import RabbitMQManager, RabbitMQRpcClient

logger = logging.getLogger("[ms-docentes notifications]")
rabbitmq = RabbitMQManager()
rpc_client = RabbitMQRpcClient()

def create_user_auth_rpc(email: str, rol: str) -> dict:
    """Llama al MS-Auth vía RPC para crear un usuario"""
    try:
        response = rpc_client.call(
            queue_name='rpc_auth_queue',
            action='crear_usuario',
            data={"email": email, "rol": rol}
        )
        return response
    except Exception as e:
        logger.error(f"Error llamando RPC crear_usuario: {e}")
        return {"success": False, "error_message": str(e)}

def send_baja_notif(alumno_data: dict, docente_data: dict, auth_token: str) -> bool:
    """Publica un evento de baja de alumno en RabbitMQ"""
    try:
        message = {
            "alumnoId": str(alumno_data['id']),
            "alumnoNombre": alumno_data['nombre'],
            "docenteId": str(docente_data['id']),
            "docenteNombre": docente_data['nombre'],
            "docenteEmail": docente_data['email'],
            "auth_token": auth_token
        }
        rabbitmq.publish_event(
            exchange='events_exchange',
            routing_key='docentes.baja',
            message=message
        )
        logger.info(f"Notificacion docentes.baja enviada para alumno: {alumno_data['id']}")
        return True
    except Exception as e:
        logger.error(f"Error enviando notificacion docentes.baja: {e}")
        return False

def send_bienvenida_notif(alumno_data: dict, materia_nombre: str, auth_token: str, clave_unica: str = None) -> bool:
    """Publica un evento de bienvenida de alumno en RabbitMQ"""
    try:
        message = {
            "alumnoId": str(alumno_data['id']),
            "alumnoNombre": alumno_data['nombre'],
            "alumnoEmail": alumno_data['email'],
            "materiaNombre": materia_nombre,
            "claveUnica": clave_unica if clave_unica else alumno_data['matricula'],
            "auth_token": auth_token
        }
        rabbitmq.publish_event(
            exchange='events_exchange',
            routing_key='periodos.bienvenida',
            message=message
        )
        logger.info(f"Notificacion periodos.bienvenida enviada para alumno: {alumno_data['id']}")
        return True
    except Exception as e:
        logger.error(f"Error enviando notificacion periodos.bienvenida: {e}")
        return False

def send_bienvenida_docente_notif(docente_data: dict, password: str, auth_token: str) -> bool:
    """Publica un evento de bienvenida de docente en RabbitMQ"""
    try:
        message = {
            "docenteId": str(docente_data['id']),
            "docenteNombre": docente_data['nombre'],
            "docenteEmail": docente_data['email'],
            "claveUnica": password,
            "auth_token": auth_token
        }
        rabbitmq.publish_event(
            exchange='events_exchange',
            routing_key='docentes.bienvenida',
            message=message
        )
        logger.info(f"Notificacion docentes.bienvenida enviada para docente: {docente_data['id']}")
        return True
    except Exception as e:
        logger.error(f"Error enviando notificacion docentes.bienvenida: {e}")
        return False
