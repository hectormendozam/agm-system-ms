import logging
from src.rabbitmq_manager import RabbitMQRpcServer
from src.database import get_db
from src import models

logger = logging.getLogger("[RabbitMQ-RPC ms-calificaciones]")

class CalificacionesRpcHandlers:
    def get_promedio_alumno(self, data):
        materia_id = data.get("materia_id")
        alumno_id = data.get("alumno_id")
        db = next(get_db())
        try:
            actividades = db.query(models.Actividad).filter(models.Actividad.materia_id == materia_id).all()
            promedio_ponderado = 0.0

            for act in actividades:
                calif = db.query(models.Calificacion).filter_by(
                    actividad_id=str(act.id), alumno_id=alumno_id
                ).first()

                if calif:
                    promedio_ponderado += calif.valor * (act.ponderacion / 100)

            return {
                "success": True,
                "promedio_final": round(promedio_ponderado, 2),
                "mensaje": "Promedio consultado exitosamente"
            }
        except Exception as e:
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    def get_concentrado_materia(self, data):
        materia_id = data.get("materia_id")
        db = next(get_db())
        try:
            actividades = db.query(models.Actividad).filter(models.Actividad.materia_id == materia_id).all()
            items = []
            for act in actividades:
                calificaciones = db.query(models.Calificacion).filter_by(actividad_id=str(act.id)).all()
                for c in calificaciones:
                    items.append({
                        "alumno_id": c.alumno_id,
                        "nota": c.valor,
                        "actividad_nombre": act.nombre
                    })
            return {"success": True, "calificaciones": items}
        except Exception as e:
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    def get_estadisticas_materia(self, data):
        materia_id = data.get("materia_id")
        db = next(get_db())
        try:
            actividades = db.query(models.Actividad).filter(models.Actividad.materia_id == materia_id).all()
            if not actividades:
                return {
                    "success": True,
                    "promedio_general": 0.0,
                    "total_alumnos_evaluados": 0,
                    "calificacion_maxima": 0.0,
                    "calificacion_minima": 0.0,
                    "aprobados": 0,
                }

            concentrado_alumnos = {}

            for act in actividades:
                calificaciones = db.query(models.Calificacion).filter_by(actividad_id=str(act.id)).all()
                for calif in calificaciones:
                    matricula = calif.alumno_id
                    puntos = calif.valor * (act.ponderacion / 100)
                    if matricula not in concentrado_alumnos:
                        concentrado_alumnos[matricula] = 0.0
                    concentrado_alumnos[matricula] += puntos

            if not concentrado_alumnos:
                return {
                    "success": True,
                    "promedio_general": 0.0,
                    "total_alumnos_evaluados": 0,
                    "calificacion_maxima": 0.0,
                    "calificacion_minima": 0.0,
                    "aprobados": 0,
                }

            promedios = list(concentrado_alumnos.values())
            aprobados = sum(1 for p in promedios if round(p) >= 6)

            return {
                "success": True,
                "promedio_general": round(sum(promedios) / len(promedios), 2),
                "total_alumnos_evaluados": len(promedios),
                "calificacion_maxima": round(max(promedios), 2),
                "calificacion_minima": round(min(promedios), 2),
                "aprobados": aprobados,
            }
        except Exception as e:
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    def get_concentrado_alumnos(self, data):
        materia_id = data.get("materia_id")
        db = next(get_db())
        try:
            actividades = db.query(models.Actividad).filter(models.Actividad.materia_id == materia_id).all()
            concentrado: dict[str, float] = {}

            for act in actividades:
                calificaciones = db.query(models.Calificacion).filter_by(actividad_id=str(act.id)).all()
                for c in calificaciones:
                    if c.alumno_id not in concentrado:
                        concentrado[c.alumno_id] = 0.0
                    concentrado[c.alumno_id] += c.valor * (act.ponderacion / 100)

            result = []
            for matricula, promedio in concentrado.items():
                promedio = round(promedio, 2)
                redondeado = int(promedio) + 1 if (promedio - int(promedio)) >= 0.5 else int(promedio)
                result.append({
                    "alumno_id": matricula,
                    "promedio_real": promedio,
                    "calificacion_final": redondeado,
                })

            return {"success": True, "alumnos": result}
        except Exception as e:
            return {"success": False, "message": str(e)}
        finally:
            db.close()

def serve():
    handlers = CalificacionesRpcHandlers()
    server = RabbitMQRpcServer(queue_name='rpc_calificaciones_queue')
    server.register_action('get_promedio_alumno', handlers.get_promedio_alumno)
    server.register_action('get_concentrado_materia', handlers.get_concentrado_materia)
    server.register_action('get_estadisticas_materia', handlers.get_estadisticas_materia)
    server.register_action('get_concentrado_alumnos', handlers.get_concentrado_alumnos)
    server.start()

if __name__ == "__main__":
    serve()
