import os
import logging
import requests as _requests
from rabbitmq_manager import RabbitMQRpcClient, RabbitMQManager

logger = logging.getLogger("[RabbitMQ-Client ms-reportes]")
rpc_client = RabbitMQRpcClient()
event_manager = RabbitMQManager()

_PERIODOS_BASE = os.getenv("MS_PERIODOS_URL", "http://ms-periodos-materias:8000")

def _materia_rest_by_nrc(nrc: str) -> dict | None:
    """Fallback REST interno a ms-periodos-materias (sin auth) cuando RabbitMQ falla."""
    try:
        r = _requests.get(f"{_PERIODOS_BASE}/api/internal/materias/{nrc}/", timeout=5)
        if not r.ok:
            return None
        data = r.json()
        return data.get("data") if data.get("success") else None
    except Exception as e:
        logger.error(f"Fallback REST get_materia_by_nrc falló: {e}")
        return None

def get_materia_by_id(materia_id: int) -> dict | None:
    """Consulta ms-periodos-materias vía RPC"""
    try:
        response = rpc_client.call(
            queue_name='rpc_periodos_queue',
            action='get_materia_by_id',
            data={"id": materia_id}
        )
        if response.get("success"):
            return response.get("data")
        return None
    except Exception as e:
        logger.error(f"Error calling get_materia_by_id: {e}")
        return None

def get_materia_by_nrc(nrc: str) -> dict | None:
    """Consulta ms-periodos-materias vía RPC, con fallback REST."""
    try:
        response = rpc_client.call(
            queue_name='rpc_periodos_queue',
            action='get_materia_by_nrc',
            data={"nrc": nrc}
        )
        if response.get("success"):
            return response.get("data")
        return None
    except Exception as e:
        logger.error(f"RPC get_materia_by_nrc falló, usando fallback REST: {e}")
        return _materia_rest_by_nrc(nrc)

def get_periodo_activo() -> dict | None:
    """Consulta ms-periodos-materias vía RPC"""
    try:
        response = rpc_client.call(
            queue_name='rpc_periodos_queue',
            action='get_periodo_activo',
            data={}
        )
        if response.get("success"):
            return response.get("data")
        return None
    except Exception as e:
        logger.error(f"Error calling get_periodo_activo: {e}")
        return None

def get_materias_by_docente(docente_id: int) -> list[dict] | None:
    """Consulta ms-periodos-materias vía RPC"""
    try:
        response = rpc_client.call(
            queue_name='rpc_periodos_queue',
            action='list_materias_by_docente',
            data={"docente_id": docente_id}
        )
        if response.get("success"):
            return response.get("data")
        return None
    except Exception as e:
        logger.error(f"Error calling get_materias_by_docente: {e}")
        return None

def get_alumnos_by_materia(materia_id: str) -> list[dict] | None:
    """Consulta ms-docentes vía RPC"""
    try:
        response = rpc_client.call(
            queue_name='rpc_docentes_queue',
            action='get_alumnos_by_materia',
            data={"materiaId": materia_id}
        )
        if response.get("success"):
            return response.get("alumnos")
        return None
    except Exception as e:
        logger.error(f"Error calling get_alumnos_by_materia: {e}")
        return None

def get_estadisticas_asistencia(materia_id: str) -> dict | None:
    """Consulta ms-asistencias vía RPC"""
    try:
        response = rpc_client.call(
            queue_name='rpc_asistencias_queue',
            action='get_estadisticas_asistencia',
            data={"materiaId": materia_id}
        )
        if response.get("success"):
            return response
        return None
    except Exception as e:
        logger.error(f"Error calling get_estadisticas_asistencia: {e}")
        return None

def publicar_reporte_generado(tipo: str, materia_id: str, formato: str, docente_id: str = None):
    """Publica evento asíncrono al generar un reporte (fire-and-forget)"""
    try:
        event_manager.publish_event(
            exchange="events_exchange",
            routing_key="reportes.generado",
            message={
                "tipo": tipo,
                "materia_id": materia_id,
                "formato": formato,
                "docente_id": docente_id,
            }
        )
    except Exception as e:
        logger.error(f"Error publicando evento reporte_generado: {e}")


def get_calificaciones_stats(materia_id: str) -> dict | None:
    """Consulta ms-calificaciones vía RPC para estadísticas de calificaciones"""
    try:
        response = rpc_client.call(
            queue_name='rpc_calificaciones_queue',
            action='get_estadisticas_materia',
            data={"materia_id": materia_id}
        )
        if response.get("success"):
            return response
        return None
    except Exception as e:
        logger.error(f"Error calling get_calificaciones_stats: {e}")
        return None

def construir_sesiones_asistencia(alumnos: list, materia_id: str) -> list:
    """
    Combina datos de alumnos con sus asistencias reales.
    Si no hay datos, devuelve una estructura vacía/demo.
    """
    sesiones = []
    try:
        for alumno in alumnos:
            resp = rpc_client.call(
                queue_name='rpc_asistencias_queue',
                action='get_asistencia_alumno',
                data={
                    "alumnoId": alumno["id"],
                    "materiaId": materia_id
                }
            )
            if resp.get("success"):
                asistencias = resp.get("asistencias", [])
                sesiones.append({
                    "alumno_id": alumno["id"],
                    "alumno_nombre": alumno["nombre"],
                    "asistencias": asistencias
                })
            else:
                sesiones.append({
                    "alumno_id": alumno["id"],
                    "alumno_nombre": alumno["nombre"],
                    "asistencias": []
                })
        return sesiones
    except Exception as e:
        logger.error(f"Error construyendo sesiones de asistencia: {e}")
        return []
