"""
controllers/alumnos_controller.py
Router FastAPI para el recurso /alumnos.
"""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Path, Header
from sqlalchemy.orm import Session
from typing import List, Optional

from database import get_db
from schemas import AlumnoResponse, ImportacionResponse, BajaResponse
from src.services import alumnos_service
from src.notifications import send_baja_notif
import models
from auth_middleware import get_current_user_rpc

router = APIRouter(prefix="/alumnos", tags=["Alumnos"], dependencies=[Depends(get_current_user_rpc)])


def _alumno_dict(alumno: models.Alumno) -> dict:
    return {
        "id": alumno.id,
        "numero_registro": alumno.numero_registro,
        "matricula": alumno.matricula,
        "nombre": alumno.nombre,
        "apellido": "",
        "email": alumno.email,
        "nrc": alumno.nrc,
        "activo": alumno.activo,
    }


@router.post(
    "/importar/{materiaId}",
    response_model=ImportacionResponse,
    summary="Importar lista de alumnos desde PDF",
    description=(
        "Recibe un archivo PDF con la lista de alumnos inscritos "
        "en la materia identificada por su NRC (materiaId). "
        "El PDF debe tener el formato de 'Resumen de lista de clase' de BUAP."
    ),
)
async def importar_alumnos(
    materiaId: str = Path(..., description="NRC de la materia"),
    archivo: UploadFile = File(None, description="Archivo PDF con la lista de alumnos"),
    file: UploadFile = File(None, description="Alias usado por algunos frontends"),
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None)
):
    archivo = archivo or file
    if archivo is None:
        raise HTTPException(status_code=400, detail="Se requiere un archivo PDF")
    if not archivo.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF (.pdf)")

    contenido = await archivo.read()
    try:
        alumnos_procesados = alumnos_service.importar_alumnos_desde_pdf(contenido, materiaId, db)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Error al procesar el PDF: {str(exc)}")

    if alumnos_procesados:
        import os
        from src.notifications import rabbitmq as _rmq
        token = authorization.replace("Bearer ", "") if authorization else "no-token"
        materia = db.query(models.MateriaDocente).filter(models.MateriaDocente.nrc == materiaId).first()
        materia_nombre = materia.nombre_materia if materia else f"NRC {materiaId}"
        whitelist = [e.strip().lower() for e in os.getenv("NOTIFY_ALUMNO_WHITELIST", "").split(",") if e.strip()]

        _rmq.publish_to_queue(
            "docentes_import_jobs_queue",
            {
                "job_type": "crear_usuarios_alumnos",
                "alumno_ids": [a["alumno"].id for a in alumnos_procesados],
                "materia_nombre": materia_nombre,
                "token": token,
                "whitelist": whitelist,
            },
        )

    return ImportacionResponse(
        mensaje=f"Importación de alumnos para NRC {materiaId} completada",
        registros_importados=len(alumnos_procesados),
    )


@router.post(
    "/importar/",
    response_model=ImportacionResponse,
    summary="Importar lista de alumnos desde PDF detectando el NRC",
)
async def importar_alumnos_auto(
    archivo: UploadFile = File(None, description="Archivo PDF con la lista de alumnos"),
    file: UploadFile = File(None, description="Alias usado por algunos frontends"),
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    archivo = archivo or file
    if archivo is None:
        raise HTTPException(status_code=400, detail="Se requiere un archivo PDF")
    if not archivo.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF (.pdf)")

    contenido = await archivo.read()
    materiaId = alumnos_service._extraer_nrc_desde_pdf(contenido)
    if not materiaId:
        raise HTTPException(status_code=422, detail="No se pudo detectar el NRC dentro del PDF")

    alumnos_nuevos = alumnos_service.importar_alumnos_desde_pdf(contenido, materiaId, db)
    if alumnos_nuevos:
        import os
        from src.notifications import rabbitmq as _rmq
        token = authorization.replace("Bearer ", "") if authorization else "no-token"
        materia = db.query(models.MateriaDocente).filter(models.MateriaDocente.nrc == materiaId).first()
        materia_nombre = materia.nombre_materia if materia else f"NRC {materiaId}"
        whitelist = [e.strip().lower() for e in os.getenv("NOTIFY_ALUMNO_WHITELIST", "").split(",") if e.strip()]

        _rmq.publish_to_queue(
            "docentes_import_jobs_queue",
            {
                "job_type": "crear_usuarios_alumnos",
                "alumno_ids": [a["alumno"].id for a in alumnos_nuevos],
                "materia_nombre": materia_nombre,
                "token": token,
                "whitelist": whitelist,
            },
        )

    return ImportacionResponse(
        mensaje=f"Importacion de alumnos para NRC {materiaId} completada",
        registros_importados=len(alumnos_nuevos),
    )


@router.get(
    "/",
    summary="Listar alumnos activos",
)
def listar_todos_los_alumnos(
    page: int = 1,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    alumnos = alumnos_service.listar_alumnos(db, search)
    return {"count": len(alumnos), "next": None, "previous": None, "results": [_alumno_dict(a) for a in alumnos]}


@router.get(
    "/materia/{materiaId}",
    response_model=List[AlumnoResponse],
    summary="Listar alumnos activos de una materia",
)
def listar_alumnos(
    materiaId: str = Path(..., description="NRC de la materia"),
    db: Session = Depends(get_db),
):
    return alumnos_service.listar_alumnos_por_materia(materiaId, db)


@router.delete(
    "/{id}/baja",
    response_model=BajaResponse,
    summary="Dar de baja a un alumno de su materia",
    description="Baja lógica: el registro permanece en BD con activo=False para conservar historial.",
)
def dar_baja_alumno(
    id: int = Path(..., description="ID del alumno en la BD"),
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None)
):
    # 1. Realizar la baja en la BD
    alumno = alumnos_service.dar_de_baja(id, db)

    # 2. Obtener datos para la notificación enriquecida
    materia_docente = db.query(models.MateriaDocente).filter(models.MateriaDocente.nrc == alumno.nrc).first()

    if materia_docente and materia_docente.docente:
        docente = materia_docente.docente
        token = authorization.replace("Bearer ", "") if authorization else "no-token"

        alumno_dict = {"id": alumno.id, "nombre": alumno.nombre}
        docente_dict = {"id": docente.id, "nombre": docente.nombre, "email": docente.email}

        send_baja_notif(alumno_dict, docente_dict, token)

    return BajaResponse(
        mensaje=f"Alumno {alumno.nombre} dado de baja correctamente",
        alumno_id=alumno.id,
        nrc=alumno.nrc,
    )


@router.delete(
    "/{id}/",
    response_model=BajaResponse,
    summary="Dar de baja a un alumno de su materia",
)
def dar_baja_alumno_alias(
    id: int = Path(..., description="ID del alumno en la BD"),
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    return dar_baja_alumno(id=id, db=db, authorization=authorization)
