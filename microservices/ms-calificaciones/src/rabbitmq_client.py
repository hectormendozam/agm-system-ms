import logging
from src.rabbitmq_manager import RabbitMQRpcClient

logger = logging.getLogger("[RabbitMQ-Client ms-calificaciones]")
rpc_client = RabbitMQRpcClient()


def get_materia_nrc(materia_id: str) -> str | None:
    """Obtiene el NRC de una materia por su ID entero via ms-periodos-materias."""
    try:
        resp = rpc_client.call(
            queue_name="rpc_periodos_queue",
            action="get_materia_by_id",
            data={"id": int(materia_id)},
        )
        if resp and resp.get("success"):
            return resp["data"].get("nrc")
        return None
    except Exception as e:
        logger.error(f"Error al obtener NRC de materia {materia_id}: {e}")
        return None


def get_alumnos_por_nrc(nrc: str) -> list:
    """Devuelve todos los alumnos activos de un NRC via ms-docentes."""
    try:
        resp = rpc_client.call(
            queue_name="rpc_docentes_queue",
            action="get_alumnos_by_materia",
            data={"materiaId": nrc},
        )
        return resp.get("alumnos", []) if resp else []
    except Exception as e:
        logger.error(f"Error al obtener alumnos del NRC {nrc}: {e}")
        return []


def get_alumno_nombre(matricula: str) -> str:
    """Devuelve el nombre de un alumno por matrícula; retorna la matrícula si no se encuentra."""
    try:
        resp = rpc_client.call(
            queue_name="rpc_docentes_queue",
            action="get_alumno_by_matricula",
            data={"matricula": matricula},
        )
        if resp and resp.get("success"):
            return resp["data"].get("nombre", matricula)
        return matricula
    except Exception as e:
        return matricula


def validar_propiedad_materia(docente_id: str, materia_id: str, docente_email: str = None) -> bool:
    """Consulta si el docente es dueño de la materia vía RPC.
    Pasa el email para resolver el docente_id real de ms-docentes (el JWT usa el id de ms-auth)."""
    try:
        data = {
            "docenteId": docente_id,
            "materiaId": materia_id,
        }
        if docente_email:
            data["docenteEmail"] = docente_email
        response = rpc_client.call(
            queue_name='rpc_docentes_queue',
            action='is_docente_en_materia',
            data=data,
        )
        return response.get("result", False)
    except Exception as e:
        logger.error(f"Error al validar propiedad de materia: {e}")
        return False