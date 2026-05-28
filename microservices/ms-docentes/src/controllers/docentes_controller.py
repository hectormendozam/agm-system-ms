"""
controllers/docentes_controller.py
Router FastAPI para el recurso /docentes.
"""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Header
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from schemas import ImportacionResponse
import models
from src.services import docentes_service
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
    summary="Importar programacion academica desde PDF",
)
async def importar_docentes(
    archivo: UploadFile = File(None, description="PDF de programacion academica"),
    file: UploadFile = File(None, description="Alias usado por algunos frontends"),
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    archivo = _resolver_archivo(archivo, file)
    contenido = await archivo.read()
    try:
        docentes = docentes_service.importar_docentes_desde_pdf(contenido, db)
        
        # Intentar crear usuarios si tienen correo
        token = authorization.replace("Bearer ", "") if authorization else "no-token"
        from src.notifications import create_user_auth_rpc, send_bienvenida_docente_notif
        import os
        whitelist_raw = os.getenv("NOTIFY_DOCENTE_WHITELIST", "")
        whitelist = [e.strip().lower() for e in whitelist_raw.split(",") if e.strip()]

        for doc in docentes:
            if doc.email:
                rpc_res = create_user_auth_rpc(doc.email, "Docente")
                if rpc_res.get("success"):
                    password = rpc_res.get("password")
                    
                    if not whitelist or doc.email.lower() in whitelist:
                        doc_dict = {"id": doc.id, "nombre": doc.nombre, "email": doc.email}
                        send_bienvenida_docente_notif(doc_dict, password, token)
                    else:
                        print(f"Skipping teacher email notification for {doc.email} (not in whitelist)")
                else:
                    print(f"Error creando usuario para {doc.email}: {rpc_res.get('error_message')}")

    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Error al procesar el PDF: {exc}")

    return ImportacionResponse(
        mensaje="Importacion de docentes completada",
        registros_importados=len(docentes),
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
        docentes = docentes_service.importar_directorio_docentes_pdf(contenido, db)
        
        # Crear usuarios para todos los docentes importados que tengan email
        token = authorization.replace("Bearer ", "") if authorization else "no-token"
        from src.notifications import create_user_auth_rpc, send_bienvenida_docente_notif
        import os
        whitelist_raw = os.getenv("NOTIFY_DOCENTE_WHITELIST", "")
        whitelist = [e.strip().lower() for e in whitelist_raw.split(",") if e.strip()]

        for doc in docentes:
            if doc.email:
                rpc_res = create_user_auth_rpc(doc.email, "Docente")
                if rpc_res.get("success"):
                    password = rpc_res.get("password")
                    
                    if not whitelist or doc.email.lower() in whitelist:
                        doc_dict = {"id": doc.id, "nombre": doc.nombre, "email": doc.email}
                        send_bienvenida_docente_notif(doc_dict, password, token)
                    else:
                        print(f"Skipping teacher email notification for {doc.email} (not in whitelist)")
                else:
                    print(f"Error creando usuario para docente {doc.email}: {rpc_res.get('error_message')}")

    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Error al procesar el PDF del directorio: {exc}")

    return ImportacionResponse(
        mensaje="Importacion del directorio docente completada",
        registros_importados=len(docentes),
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


@router.get(
    "/{docente_id}/materias/",
    summary="Listar materias de un docente",
)
def listar_materias_docente(docente_id: int, db: Session = Depends(get_db)):
    docente = db.query(models.Docente).filter(models.Docente.id == docente_id).first()
    if docente is None:
        raise HTTPException(status_code=404, detail=f"Docente {docente_id} no encontrado")

    materias = [
        {
            "id": materia.id,
            "nrc": materia.nrc,
            "nombre": materia.nombre_materia,
            "nombre_materia": materia.nombre_materia,
            "seccion": materia.seccion,
            "clave": materia.clave,
            "horario": materia.horario,
        }
        for materia in docente.materias
    ]

    return {"data": materias}
