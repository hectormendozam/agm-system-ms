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

def get_concentrado_alumnos(materia_id: str) -> list:
    """Obtiene el concentrado de calificaciones por alumno vía ms-calificaciones RPC."""
    try:
        response = rpc_client.call(
            queue_name='rpc_calificaciones_queue',
            action='get_concentrado_alumnos',
            data={"materia_id": materia_id}
        )
        if response.get("success"):
            return response.get("alumnos", [])
        return []
    except Exception as e:
        logger.error(f"Error calling get_concentrado_alumnos: {e}")
        return []


def construir_sesiones_asistencia(alumnos: list, materia_db_id: str) -> list:
    """
    Obtiene las asistencias reales de cada alumno y las agrupa por fecha de sesión.
    materia_db_id debe ser el ID entero de ms-periodos-materias (no el NRC).
    Retorna: [{fecha: str, alumnos: [{matricula, nombre, estado, hora}]}]
    """
    from collections import defaultdict
    sesiones_por_fecha: dict[str, list] = defaultdict(list)

    try:
        for alumno in alumnos:
            resp = rpc_client.call(
                queue_name='rpc_asistencias_queue',
                action='get_asistencia_alumno',
                data={"alumnoId": str(alumno["id"]), "materiaId": materia_db_id}
            )
            if not resp.get("success"):
                continue
            for reg in resp.get("asistencias", []):
                hr = reg.get("hora_registro", "")
                fecha = hr.split(" ")[0] if " " in hr else hr[:10]
                hora = hr.split(" ")[1][:5] if " " in hr else "—"
                if not fecha:
                    continue
                sesiones_por_fecha[fecha].append({
                    "matricula": str(alumno.get("matricula", alumno["id"])),
                    "nombre": alumno.get("nombre", ""),
                    "estado": reg.get("estado", "Presente"),
                    "hora": hora,
                })

        return [
            {"fecha": fecha, "alumnos": alumnos_list}
            for fecha, alumnos_list in sorted(sesiones_por_fecha.items())
        ]
    except Exception as e:
        logger.error(f"Error construyendo sesiones de asistencia: {e}")
        return []
