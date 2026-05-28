"""
controllers/docentes_controller.py
Router FastAPI para el recurso /docentes.
"""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Path, Header
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from schemas import ImportacionResponse, BajaDocenteResponse
from src.services import docentes_service
from src.notifications import rabbitmq as _rmq
from auth_middleware import get_current_user_rpc

router = APIRouter(prefix="/docentes", tags=["Docentes"], dependencies=[Depends(get_current_user_rpc)])


def _docente_dict(docente) -> dict:
    return {
        "id": docente.id,
        "nombre": docente.nombre,
        "apellido": "",
        "email": docente.email,
        "clave_empleado": "",
        "departamento": docente.departamento,
        "activo": docente.activo,
        "materias": [
            {
                "id": materia.id,
                "nrc": materia.nrc,
                "nombre_materia": materia.nombre_materia,
                "seccion": materia.seccion,
                "clave": materia.clave,
                "horario": materia.horario,
            }
            for materia in docente.materias
        ],
    }


def _resolver_archivo(archivo: UploadFile | None, file: UploadFile | None) -> UploadFile:
    resolved = archivo or file
    if resolved is None:
        raise HTTPException(status_code=400, detail="Se requiere un archivo PDF")
    if not resolved.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF")
    return resolved


@router.post(
    "/importar",
    response_model=ImportacionResponse,
    summary="Importar docentes desde PDF (Auto-detección)",
)
async def importar_docentes(
    archivo: UploadFile = File(None, description="PDF de programacion academica o directorio"),
    file: UploadFile = File(None, description="Alias usado por algunos frontends"),
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None)
):
    archivo = _resolver_archivo(archivo, file)
    contenido = await archivo.read()
    try:
        # 1. Intentar como programación académica (formato Materias/NRC)
        total = docentes_service.importar_docentes_desde_pdf(contenido, db)
        
        # 2. Si no se importó nada, intentar como directorio de Personal Docente
        if total == 0:
            total = docentes_service.importar_directorio_docentes_pdf(contenido, db)
            mensaje = "Importacion del directorio docente completada"
        else:
            mensaje = "Importacion de docentes (programacion academica) completada"
            
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=422, detail=f"Error al procesar el PDF: {exc}")

    docentes = docentes_service.buscar_docentes(db)
    import os
    token = authorization.replace("Bearer ", "") if authorization else "no-token"
    _rmq.publish_to_queue(
        "docentes_import_jobs_queue",
        {
            "job_type": "crear_usuarios_docentes",
            "docente_ids": [d.id for d in docentes],
            "token": token,
            "whitelist": [e.strip().lower() for e in os.getenv("NOTIFY_DOCENTE_WHITELIST", "").split(",") if e.strip()],
        },
    )
    return ImportacionResponse(
        mensaje=mensaje,
        registros_importados=total,
    )


@router.post(
    "/importar-directorio",
    response_model=ImportacionResponse,
    summary="Importar informacion adicional de Personal Docente desde PDF",
)
async def importar_directorio_docentes(
    archivo: UploadFile = File(None, description="PDF de directorio de personal docente"),
    file: UploadFile = File(None, description="Alias usado por algunos frontends"),
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    archivo = _resolver_archivo(archivo, file)
    contenido = await archivo.read()
    try:
        total = docentes_service.importar_directorio_docentes_pdf(contenido, db)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Error al procesar el PDF del directorio: {exc}")

    docentes = docentes_service.buscar_docentes(db)
    import os
    token = authorization.replace("Bearer ", "") if authorization else "no-token"
    _rmq.publish_to_queue(
        "docentes_import_jobs_queue",
        {
            "job_type": "crear_usuarios_docentes",
            "docente_ids": [d.id for d in docentes],
            "token": token,
            "whitelist": [e.strip().lower() for e in os.getenv("NOTIFY_DOCENTE_WHITELIST", "").split(",") if e.strip()],
        },
    )

    return ImportacionResponse(
        mensaje="Importacion del directorio docente completada",
        registros_importados=total,
    )


@router.get(
    "/",
    summary="Listar todos los docentes",
)
def listar_docentes(
    page: int = 1,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    docentes = docentes_service.buscar_docentes(db, search)
    return {"count": len(docentes), "next": None, "previous": None, "results": [_docente_dict(d) for d in docentes]}


@router.delete(
    "/{id}/baja",
    response_model=BajaDocenteResponse,
    summary="Dar de baja a un docente",
    description="Baja logica: el registro permanece en BD con activo=False para conservar historial.",
)
def dar_baja_docente(
    id: int = Path(..., description="ID del docente en la BD"),
    db: Session = Depends(get_db),
):
    docente = docentes_service.dar_de_baja_docente(id, db)
    return BajaDocenteResponse(
        mensaje=f"Docente {docente.nombre} dado de baja correctamente",
        docente_id=docente.id,
    )


@router.delete(
    "/{id}/",
    response_model=BajaDocenteResponse,
    summary="Dar de baja a un docente",
)
def dar_baja_docente_alias(
    id: int = Path(..., description="ID del docente en la BD"),
    db: Session = Depends(get_db),
):
    return dar_baja_docente(id=id, db=db)
