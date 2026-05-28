import logging
from rabbitmq_manager import RabbitMQRpcServer
from database import SessionLocal
import models

logger = logging.getLogger("[RabbitMQ-RPC ms-docentes]")

class DocentesRpcHandlers:
    def _materia_matches(self, materia, materia_id):
        materia_id_str = str(materia_id)
        return str(materia.id) == materia_id_str or materia.nrc == materia_id_str

    def get_alumno(self, data):
        alumno_id = data.get("alumnoId")
        db = SessionLocal()
        try:
            alumno = db.query(models.Alumno).filter(models.Alumno.id == int(alumno_id)).first()
            if alumno:
                return {
                    "success": True,
                    "data": {"nombre": alumno.nombre, "email": alumno.email}
                }
            return {"success": False, "message": "Alumno no encontrado"}
        except Exception as e:
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    def get_alumnos_by_materia(self, data):
        materia_id = data.get("materiaId")
        db = SessionLocal()
        try:
            alumnos = (
                db.query(models.Alumno)
                .filter(
                    models.Alumno.nrc == str(materia_id),
                    models.Alumno.activo == True,
                )
                .all()
            )
            return {
                "success": True,
                "alumnos": [
                    {"id": str(a.id), "nombre": a.nombre, "email": a.email or "", "matricula": a.matricula}
                    for a in alumnos
                ]
            }
        except Exception as e:
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    def get_alumno_by_id(self, data):
        alumno_id = data.get("id")
        db = SessionLocal()
        try:
            from sqlalchemy import text
            # Consulta cruda para asegurar que traemos la matrícula sin depender del modelo
            query = text("SELECT nombre, matricula FROM alumnos WHERE id = :aid")
            result = db.execute(query, {"aid": int(alumno_id)}).fetchone()
            
            if not result:
                return {"success": False, "message": "Alumno no encontrado"}
                
            return {
                "success": True,
                "data": {
                    "id": str(alumno_id),
                    "nombre": result[0],
                    "matricula": result[1] if result[1] else "Sin Matricula"
                }
            }
        except Exception as e:
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    def get_docente_by_id(self, data):
        docente_id = data.get("id")
        db = SessionLocal()
        try:
            docente = db.query(models.Docente).filter(
                models.Docente.id == int(docente_id)
            ).first()
            if not docente:
                return {"success": False, "message": "Docente no encontrado"}
            return {
                "success": True,
                "data": {
                    "id": str(docente.id),
                    "nombre": docente.nombre,
                    "email": docente.email or "",
                }
            }
        except Exception as e:
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    def is_alumno_en_materia(self, data):
        alumno_id = data.get("alumnoId")
        materia_id = data.get("materiaId")
        db = SessionLocal()
        try:
            alumno = db.query(models.Alumno).filter(
                models.Alumno.id == int(alumno_id),
                models.Alumno.activo == True
            ).first()
            if not alumno:
                return {"success": True, "result": False}

            materia = db.query(models.MateriaDocente).filter(
                (models.MateriaDocente.id == int(materia_id)) |
                (models.MateriaDocente.nrc == str(materia_id))
            ).first()
            if not materia:
                return {"success": True, "result": False}

            result = alumno.nrc == materia.nrc
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    def is_docente_en_materia(self, data):
        docente_id = data.get("docenteId")
        materia_id = data.get("materiaId")
        docente_email = data.get("docenteEmail")
        db = SessionLocal()
        try:
            # Si viene email, resolver primero el docente_id real de ms-docentes
            # (el JWT usa el id de ms-auth que puede diferir del id de ms-docentes)
            if docente_email:
                docente = db.query(models.Docente).filter(
                    models.Docente.email == docente_email
                ).first()
                if docente:
                    docente_id = str(docente.id)

            materia = db.query(models.MateriaDocente).filter(
                models.MateriaDocente.docente_id == int(docente_id),
                (models.MateriaDocente.id == int(materia_id)) |
                (models.MateriaDocente.nrc == str(materia_id))
            ).first()
            return {"success": True, "result": bool(materia)}
        except Exception as e:
            return {"success": False, "message": str(e)}
        finally:
            db.close()

def serve():
    handlers = DocentesRpcHandlers()
    server = RabbitMQRpcServer(queue_name='rpc_docentes_queue')
    server.register_action('get_alumno', handlers.get_alumno)
    server.register_action('get_alumnos_by_materia', handlers.get_alumnos_by_materia)
    server.register_action('get_alumno_by_id', handlers.get_alumno_by_id)
    server.register_action('get_docente_by_id', handlers.get_docente_by_id)
    server.register_action('is_alumno_en_materia', handlers.is_alumno_en_materia)
    server.register_action('is_docente_en_materia', handlers.is_docente_en_materia)
    server.start()

if __name__ == "__main__":
    serve()
