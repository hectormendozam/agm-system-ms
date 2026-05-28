import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import engine, Base, get_db
from auth_middleware import require_roles
import models, schemas, rabbitmq_client
from generadores import (
    generar_excel_calificaciones, generar_pdf_calificaciones,
    generar_excel_asistencias,    generar_pdf_asistencias,
)

Base.metadata.create_all(bind=engine)

# Migración inline: agrega columna si no existe (PostgreSQL)
def _migrate():
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE estadisticas_materia ADD COLUMN IF NOT EXISTS porcentaje_asistencia FLOAT DEFAULT 0"
            ))
            conn.commit()
    except Exception:
        pass

_migrate()


def _start_rabbitmq():
    try:
        import rabbitmq_server
        rabbitmq_server.serve()
    except Exception as e:
        print(f"[WARNING] No se pudo iniciar el servidor RabbitMQ-RPC: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    rb_thread = threading.Thread(target=_start_rabbitmq, daemon=True)
    rb_thread.start()
    yield


app = FastAPI(
    title="MS-7 Reportes & Estadísticas",
    description="Microservicio de Reportes y Estadísticas para el sistema AGM — BUAP FCC",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────

from starlette.requests import Request as StarletteRequest

@app.middleware("http")
async def strip_service_prefix(request: StarletteRequest, call_next):
    """Gateway adds /reportes prefix to all paths. /estadisticas/* and /historial
    routes don't have that prefix, so strip it for them."""
    path = request.scope["path"]
    for sub in ("/estadisticas", "/historial"):
        if path.startswith(f"/reportes{sub}"):
            request.scope["path"] = path[len("/reportes"):]
            break
    return await call_next(request)

origins = [
    "https://agm-system-frontend-joselyn-agm.vercel.app",
    "https://agm-system-frontend-30ytwlq1y-joselyn-agm.vercel.app",
    "https://agm-system-frontend.vercel.app",
    "http://localhost:4200",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


# ── Health check (público) ───────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def read_root():
    return {"mensaje": "¡El microservicio de Reportes está corriendo!", "servicio": "ms-reportes"}


# ── Reportes – Calificaciones ─────────────────────────────────────────────────

@app.get(
    "/reportes/calificaciones/{materia_id}",
    summary="Descargar reporte de calificaciones",
    tags=["Reportes"],
)
def reporte_calificaciones(
    materia_id: str,
    formato: str = Query(default="pdf", enum=["pdf", "xls"]),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("Administrador", "Docente")),
):
    try:
        materia_info = rabbitmq_client.get_materia_by_nrc(materia_id)
        if not materia_info:
            raise HTTPException(
                status_code=503,
                detail="No se pudo obtener la información de la materia. Verifica que ms-periodos-materias esté disponible.",
            )

        alumnos = rabbitmq_client.get_alumnos_by_materia(materia_id) or []
        concentrado = rabbitmq_client.get_concentrado_alumnos(materia_id)
        grades_by_matricula = {c["alumno_id"]: c for c in concentrado}

        datos = {
            "materia_nombre": materia_info["nombre"],
            "materia_nrc":    materia_info["nrc"],
            "periodo":        "Período Activo",
            "docente":        materia_info.get("docente_nombre", ""),
            "alumnos": [
                {
                    "matricula": a.get("matricula", str(a["id"])),
                    "nombre": a["nombre"],
                    "promedio_real": grades_by_matricula.get(
                        a.get("matricula", ""), {}
                    ).get("promedio_real", 0),
                    "calificacion_final": grades_by_matricula.get(
                        a.get("matricula", ""), {}
                    ).get("calificacion_final", 0),
                }
                for a in alumnos
            ],
        }

        if formato == "xls":
            file_bytes, filename = generar_excel_calificaciones(materia_id, datos)
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            file_bytes, filename = generar_pdf_calificaciones(materia_id, datos)
            media_type = "application/pdf"

        db.add(models.ReporteGenerado(materia_id=materia_id, tipo="calificaciones", formato=formato))
        db.commit()

        rabbitmq_client.publicar_reporte_generado(
            tipo="calificaciones",
            materia_id=materia_id,
            formato=formato,
        )

        return Response(
            content=file_bytes,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar el reporte: {str(e)}")


@app.post(
    "/reportes/calificaciones/{materia_id}",
    summary="Generar reporte de calificaciones con datos reales",
    tags=["Reportes"],
)
def reporte_calificaciones_con_datos(
    materia_id: str,
    body: schemas.DatosCalificacionesReporte,
    formato: str = Query(default="pdf", enum=["pdf", "xls"]),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("Administrador", "Docente")),
):
    try:
        datos = body.model_dump()
        datos["materia_id"] = materia_id
        datos["alumnos"] = [a.model_dump() for a in body.alumnos]

        if formato == "xls":
            file_bytes, filename = generar_excel_calificaciones(materia_id, datos)
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            file_bytes, filename = generar_pdf_calificaciones(materia_id, datos)
            media_type = "application/pdf"

        db.add(models.ReporteGenerado(
            materia_id=materia_id,
            docente_id=body.docente_id,
            tipo="calificaciones",
            formato=formato,
        ))
        db.commit()

        rabbitmq_client.publicar_reporte_generado(
            tipo="calificaciones",
            materia_id=materia_id,
            formato=formato,
            docente_id=str(body.docente_id) if body.docente_id else None,
        )

        return Response(
            content=file_bytes,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar el reporte: {str(e)}")


# ── Reportes – Asistencias ────────────────────────────────────────────────────

@app.get(
    "/reportes/asistencias/{materia_id}",
    summary="Descargar reporte de asistencias",
    tags=["Reportes"],
)
def reporte_asistencias(
    materia_id: str,
    formato: str = Query(default="pdf", enum=["pdf", "xls"]),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("Administrador", "Docente")),
):
    try:
        materia_info = rabbitmq_client.get_materia_by_nrc(materia_id)
        if not materia_info:
            raise HTTPException(
                status_code=503,
                detail="No se pudo obtener la información de la materia. Verifica que ms-periodos-materias esté disponible.",
            )

        alumnos      = rabbitmq_client.get_alumnos_by_materia(materia_id) or []
        materia_db_id = str(materia_info["id"])
        sesiones = rabbitmq_client.construir_sesiones_asistencia(alumnos, materia_db_id)

        datos = {
            "materia_nombre": materia_info["nombre"],
            "materia_nrc":    materia_info["nrc"],
            "periodo":        "Período Activo",
            "docente":        materia_info.get("docente_nombre", ""),
            "sesiones":       sesiones,
        }

        if formato == "xls":
            file_bytes, filename = generar_excel_asistencias(materia_id, datos)
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            file_bytes, filename = generar_pdf_asistencias(materia_id, datos)
            media_type = "application/pdf"

        db.add(models.ReporteGenerado(materia_id=materia_id, tipo="asistencias", formato=formato))
        db.commit()

        rabbitmq_client.publicar_reporte_generado(
            tipo="asistencias",
            materia_id=materia_id,
            formato=formato,
        )

        return Response(
            content=file_bytes,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar el reporte: {str(e)}")


@app.post(
    "/reportes/asistencias/{materia_id}",
    summary="Generar reporte de asistencias con datos reales",
    tags=["Reportes"],
)
def reporte_asistencias_con_datos(
    materia_id: str,
    body: schemas.DatosAsistenciasReporte,
    formato: str = Query(default="pdf", enum=["pdf", "xls"]),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("Administrador", "Docente")),
):
    try:
        datos = body.model_dump()
        datos["materia_id"] = materia_id

        if formato == "xls":
            file_bytes, filename = generar_excel_asistencias(materia_id, datos)
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            file_bytes, filename = generar_pdf_asistencias(materia_id, datos)
            media_type = "application/pdf"

        db.add(models.ReporteGenerado(
            materia_id=materia_id,
            docente_id=body.docente_id,
            tipo="asistencias",
            formato=formato,
        ))
        db.commit()

        rabbitmq_client.publicar_reporte_generado(
            tipo="asistencias",
            materia_id=materia_id,
            formato=formato,
            docente_id=str(body.docente_id) if body.docente_id else None,
        )

        return Response(
            content=file_bytes,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar el reporte: {str(e)}")


# ── Estadísticas – Docente ────────────────────────────────────────────────────

@app.get(
    "/estadisticas/docente/{docente_id}",
    response_model=schemas.RespuestaPaginadaEstadisticasMateria,
    summary="Historial paginado de estadísticas de un docente por periodo",
    tags=["Estadísticas"],
)
def estadisticas_docente(
    docente_id: str,
    page:  int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("Administrador", "Docente")),
):
    offset = (page - 1) * limit
    query  = db.query(models.EstadisticaMateria).filter(
        models.EstadisticaMateria.docente_id == docente_id
    )
    total    = query.count()
    registros = query.order_by(models.EstadisticaMateria.fecha_registro.desc()).offset(offset).limit(limit).all()

    return {
        "success": True,
        "message": f"{total} registro(s) encontrados para el docente {docente_id}",
        "data": {"total": total, "page": page, "limit": limit, "items": registros},
    }


class AutoEstadisticasBody(BaseModel):
    docente_id: str


@app.post(
    "/estadisticas/auto/{materia_nrc}",
    response_model=schemas.RespuestaEstadistica,
    status_code=201,
    summary="Auto-calcular y registrar estadísticas al cerrar una materia",
    tags=["Estadísticas"],
)
def auto_registrar_estadisticas(
    materia_nrc: str,
    body: AutoEstadisticasBody,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("Administrador", "Docente")),
):
    materia = rabbitmq_client.get_materia_by_nrc(materia_nrc)
    if not materia:
        raise HTTPException(status_code=404, detail=f"Materia con NRC {materia_nrc} no encontrada.")

    periodo = rabbitmq_client.get_periodo_activo()
    periodo_nombre = periodo["nombre"] if periodo else "Período Activo"

    calif_stats = rabbitmq_client.get_calificaciones_stats(materia_nrc)
    promedio_general = float(calif_stats.get("promedio_general", 0.0)) if calif_stats else 0.0
    total_alumnos    = int(calif_stats.get("total_alumnos_evaluados", 0)) if calif_stats else 0

    asist_stats = rabbitmq_client.get_estadisticas_asistencia(materia_nrc)
    porcentaje_asistencia = 0.0
    if asist_stats:
        porcentaje_asistencia = float(
            asist_stats.get("porcentaje_asistencia")
            or asist_stats.get("porcentaje_promedio")
            or 0.0
        )

    porcentaje_aprobados = 0.0
    if calif_stats and total_alumnos > 0:
        aprobados = int(calif_stats.get("aprobados", 0))
        porcentaje_aprobados = round(aprobados / total_alumnos * 100, 2)

    nuevo = models.EstadisticaMateria(
        materia_id=str(materia["id"]),
        materia_nombre=materia["nombre"],
        materia_nrc=materia_nrc,
        periodo_nombre=periodo_nombre,
        docente_id=body.docente_id,
        total_alumnos=total_alumnos,
        promedio_general=promedio_general,
        porcentaje_aprobados=porcentaje_aprobados,
        porcentaje_asistencia=porcentaje_asistencia,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return {"success": True, "message": "Estadísticas registradas correctamente", "data": nuevo}


@app.post(
    "/estadisticas/registrar",
    response_model=schemas.RespuestaEstadistica,
    status_code=201,
    summary="Registrar estadísticas de una materia cerrada",
    tags=["Estadísticas"],
)
def registrar_estadisticas(
    estadistica: schemas.EstadisticaMateriaCreate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("Administrador")),
):
    nuevo = models.EstadisticaMateria(**estadistica.model_dump())
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return {"success": True, "message": "Estadísticas registradas correctamente", "data": nuevo}


# ── Estadísticas – Alumno ─────────────────────────────────────────────────────

@app.get(
    "/estadisticas/alumno/{alumno_id}",
    response_model=schemas.RespuestaPaginadaEstadisticasAlumno,
    summary="Estadísticas paginadas de un alumno por materia",
    tags=["Estadísticas"],
)
def estadisticas_alumno(
    alumno_id: str,
    page:  int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("Administrador", "Docente", "Alumno")),
):
    offset = (page - 1) * limit
    query  = db.query(models.EstadisticaAlumno).filter(
        models.EstadisticaAlumno.alumno_id == alumno_id
    )
    total     = query.count()
    registros = query.order_by(models.EstadisticaAlumno.fecha_registro.desc()).offset(offset).limit(limit).all()

    return {
        "success": True,
        "message": f"{total} materia(s) encontradas para el alumno {alumno_id}",
        "data": {"total": total, "page": page, "limit": limit, "items": registros},
    }


@app.post(
    "/estadisticas/alumno/registrar",
    response_model=schemas.RespuestaEstadisticaAlumno,
    status_code=201,
    summary="Registrar estadísticas de un alumno en una materia",
    tags=["Estadísticas"],
)
def registrar_estadisticas_alumno(
    estadistica: schemas.EstadisticaAlumnoCreate,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("Administrador")),
):
    nuevo = models.EstadisticaAlumno(**estadistica.model_dump())
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return {"success": True, "message": "Estadísticas del alumno registradas correctamente", "data": nuevo}


# ── Historial de reportes generados ──────────────────────────────────────────

@app.get(
    "/reportes/historial",
    summary="Historial paginado de todos los reportes generados",
    tags=["Reportes"],
)
def historial_reportes(
    page:  int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_roles("Administrador")),
):
    offset = (page - 1) * limit
    total  = db.query(models.ReporteGenerado).count()
    items  = db.query(models.ReporteGenerado).offset(offset).limit(limit).all()
    return {
        "success": True,
        "message": f"Página {page} de reportes",
        "data": {
            "total": total,
            "page":  page,
            "limit": limit,
            "items": [schemas.ReporteGeneradoResponse.model_validate(i) for i in items],
        },
    }
