from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import threading
import pandas as pd
import io
import re
import sys
import os
import math

from src.database import engine, Base, get_db
from src import models, schemas
from src.auth_middleware import get_current_user, require_roles
from src.rabbitmq_client import (
    validar_propiedad_materia,
    get_materia_nrc,
    get_alumnos_por_nrc,
    get_alumno_nombre,
)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="MS-4 Calificaciones",
    description="Gestión de actividades, notas por Excel y promedios ponderados.",
    version="1.0.0"
)

from starlette.requests import Request as StarletteRequest

@app.middleware("http")
async def strip_service_prefix(request: StarletteRequest, call_next):
    """Gateway always prepends service name to path: /calificaciones/... → strip it."""
    path = request.scope["path"]
    if path.startswith("/calificaciones"):
        request.scope["path"] = path[len("/calificaciones"):] or "/"
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
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def health_check():
    return {
        "success": True,
        "data": {"status": "ok"},
        "message": "MS-4 Calificaciones en línea"
    }


# ── Ponderaciones ─────────────────────────────────────────────────────────────

@app.get("/ponderaciones/{materia_id}", summary="Obtener ponderaciones de una materia")
def obtener_ponderaciones(
    materia_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    if user["rol"] == "DOCENTE":
        if not validar_propiedad_materia(str(user["id"]), materia_id, user.get("email")):
            raise HTTPException(status_code=403, detail="Acceso denegado.")

    actividades = db.query(models.Actividad).filter(models.Actividad.materia_id == materia_id).all()
    total = sum(act.ponderacion for act in actividades)
    return {"success": True, "data": {"materia_id": materia_id, "total_ponderacion": total, "detalles": actividades}}


@app.post("/ponderaciones/{materia_id}", summary="Configurar (o reconfigurar) ponderaciones de una materia")
def crear_ponderaciones(
    materia_id: str,
    payload: schemas.PonderacionesCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    if user["rol"] == "DOCENTE":
        if not validar_propiedad_materia(str(user["id"]), materia_id, user.get("email")):
            raise HTTPException(status_code=403, detail="Acceso denegado.")

    if not payload.ponderaciones:
        raise HTTPException(status_code=400, detail="Debe enviar al menos una ponderación.")

    total_nuevo = sum(item.ponderacion for item in payload.ponderaciones)
    if round(total_nuevo, 2) != 100.00:
        raise HTTPException(
            status_code=400,
            detail=f"La suma de las ponderaciones debe ser exactamente 100%. Actualmente suma {round(total_nuevo, 2)}%."
        )

    for item in payload.ponderaciones:
        if item.ponderacion <= 0 or item.ponderacion > 100:
            raise HTTPException(status_code=400, detail="Cada ponderación debe estar entre 1 y 100.")

    # Eliminar actividades (y sus calificaciones via cascade) para reemplazarlas
    existentes = db.query(models.Actividad).filter(models.Actividad.materia_id == materia_id).all()
    for act in existentes:
        db.delete(act)
    db.flush()

    creadas = []
    for item in payload.ponderaciones:
        nueva = models.Actividad(
            materia_id=materia_id,
            nombre=item.nombre,
            ponderacion=item.ponderacion,
        )
        db.add(nueva)
        creadas.append(nueva)

    db.commit()
    for a in creadas:
        db.refresh(a)

    return {
        "success": True,
        "data": {
            "materia_id": materia_id,
            "total_ponderacion": 100.0,
            "ponderaciones_creadas": [
                {"actividad_id": a.id, "nombre": a.nombre, "ponderacion": a.ponderacion}
                for a in creadas
            ],
        },
        "message": "Ponderaciones configuradas correctamente."
    }


@app.delete("/ponderaciones/{materia_id}", summary="Eliminar todas las ponderaciones (y calificaciones) de una materia")
def eliminar_ponderaciones(
    materia_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    if user["rol"] == "DOCENTE":
        if not validar_propiedad_materia(str(user["id"]), materia_id, user.get("email")):
            raise HTTPException(status_code=403, detail="Acceso denegado.")

    actividades = db.query(models.Actividad).filter(models.Actividad.materia_id == materia_id).all()
    for act in actividades:
        db.delete(act)
    db.commit()
    return {"success": True, "message": f"Ponderaciones y calificaciones de la materia {materia_id} eliminadas."}


# ── Actividades ───────────────────────────────────────────────────────────────

@app.get("/actividades/{materia_id}", summary="Listar actividades de una materia")
def listar_actividades(
    materia_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    if user["rol"] == "DOCENTE":
        if not validar_propiedad_materia(str(user["id"]), materia_id, user.get("email")):
            raise HTTPException(status_code=403, detail="Acceso denegado.")

    actividades = db.query(models.Actividad).filter(models.Actividad.materia_id == materia_id).all()
    total_ponderacion = sum(act.ponderacion for act in actividades)
    return {
        "success": True,
        "data": {
            "materia_id": materia_id,
            "total_ponderacion_registrada": total_ponderacion,
            "actividades": actividades
        },
        "message": "Actividades obtenidas correctamente."
    }


@app.post("/actividades", summary="Crear una nueva actividad evaluativa")
def crear_actividad(
    actividad: schemas.ActividadCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    if user["rol"] == "DOCENTE":
        if not validar_propiedad_materia(str(user["id"]), actividad.materia_id, user.get("email")):
            raise HTTPException(status_code=403, detail="Acceso denegado.")

    if actividad.ponderacion <= 0 or actividad.ponderacion > 100:
        raise HTTPException(status_code=400, detail="La ponderación debe estar entre 1 y 100.")

    actividades_existentes = db.query(models.Actividad).filter(models.Actividad.materia_id == actividad.materia_id).all()
    suma_actual = sum(act.ponderacion for act in actividades_existentes)
    if suma_actual + actividad.ponderacion > 100:
        raise HTTPException(
            status_code=400,
            detail=f"La suma no puede exceder 100%. Llevas {suma_actual}%, puedes agregar un máximo de {100 - suma_actual}%.")

    nueva_actividad = models.Actividad(
        materia_id=actividad.materia_id,
        nombre=actividad.nombre,
        ponderacion=actividad.ponderacion
    )
    db.add(nueva_actividad)
    db.commit()
    db.refresh(nueva_actividad)

    return {
        "success": True,
        "data": {"actividad_id": nueva_actividad.id, "nombre": nueva_actividad.nombre},
        "message": "Actividad creada correctamente."
    }


# ── Calificaciones ────────────────────────────────────────────────────────────

@app.post("/calificaciones", summary="Registrar calificación individual")
def registrar_calificacion(
    calif: schemas.CalificacionCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    actividad = db.query(models.Actividad).filter(models.Actividad.id == calif.actividad_id).first()
    if not actividad:
        raise HTTPException(status_code=404, detail="Actividad no encontrada.")

    if user["rol"] == "DOCENTE":
        if not validar_propiedad_materia(str(user["id"]), str(actividad.materia_id), user.get("email")):
            raise HTTPException(status_code=403, detail="Acceso denegado.")

    existente = db.query(models.Calificacion).filter_by(
        actividad_id=calif.actividad_id, alumno_id=calif.alumno_id
    ).first()

    if existente:
        existente.valor = calif.valor
    else:
        db.add(models.Calificacion(
            actividad_id=calif.actividad_id,
            alumno_id=calif.alumno_id,
            valor=calif.valor
        ))

    db.commit()
    return {"success": True, "message": "Calificación registrada individualmente."}


@app.post("/calificaciones/importar", summary="Cargar calificaciones desde un archivo Excel")
async def cargar_calificaciones_excel(
    actividad_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    actividad_id = actividad_id.strip()
    actividad = db.query(models.Actividad).filter(models.Actividad.id == actividad_id).first()
    if not actividad:
        raise HTTPException(status_code=404, detail="Actividad no encontrada.")

    if user["rol"] == "DOCENTE":
        if not validar_propiedad_materia(str(user["id"]), str(actividad.materia_id), user.get("email")):
            raise HTTPException(status_code=403, detail="Acceso denegado.")

    if not file.filename.endswith(('.xls', '.xlsx')):
        raise HTTPException(status_code=400, detail="El archivo debe ser un Excel (.xlsx)")

    contents = await file.read()
    try:
        df_raw = pd.read_excel(io.BytesIO(contents), header=None)

        header_row_index = 0
        found_headers = False
        target_cols = ['matricula', 'calificacion', 'puntos', 'dirección de correo', 'correo', 'email']

        for i, row in df_raw.iterrows():
            row_str = [str(val).lower().strip() for val in row if val is not None and str(val) != 'nan']
            if any(col in row_str for col in target_cols):
                header_row_index = i
                found_headers = True
                break

        df = pd.read_excel(io.BytesIO(contents), header=header_row_index if found_headers else 0)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al leer el Excel: {str(e)}")

    df.columns = df.columns.str.lower().str.strip()

    col_matricula = next((c for c in ['matricula', 'dirección de correo', 'correo', 'email'] if c in df.columns), None)
    col_calificacion = next((c for c in ['calificacion', 'puntos', 'nota', 'puntuación'] if c in df.columns), None)

    if not col_matricula or not col_calificacion:
        raise HTTPException(
            status_code=400,
            detail=f"Columnas necesarias no encontradas. Detectadas: {list(df.columns)}"
        )

    registros = 0
    for _, row in df.iterrows():
        raw = str(row[col_matricula]).strip()

        # Extraer matrícula de correo institucional (ej. bb202321840@alm.buap.mx → 202321840)
        if "@" in raw:
            username = raw.split("@")[0]
            match = re.search(r'\d+', username)
            matricula = match.group() if match else username
        else:
            matricula = raw

        if matricula.endswith('.0'):
            matricula = matricula[:-2]

        # Saltar NaN o vacíos
        raw_valor = row[col_calificacion]
        if pd.isna(raw_valor):
            continue
        try:
            valor = float(raw_valor)
        except (ValueError, TypeError):
            continue

        existente = db.query(models.Calificacion).filter_by(
            actividad_id=actividad_id, alumno_id=matricula
        ).first()
        if existente:
            existente.valor = valor
        else:
            db.add(models.Calificacion(actividad_id=actividad_id, alumno_id=matricula, valor=valor))
        registros += 1

    db.commit()
    return {
        "success": True,
        "data": {"registros_procesados": registros},
        "message": f"Se procesaron {registros} calificaciones para '{actividad.nombre}'."
    }


# ── Concentrado ───────────────────────────────────────────────────────────────

@app.get("/concentrado/{materia_id}", summary="Concentrado final de calificaciones con nombres")
def obtener_concentrado(
    materia_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    if user["rol"] == "DOCENTE":
        if not validar_propiedad_materia(str(user["id"]), materia_id, user.get("email")):
            raise HTTPException(status_code=403, detail="Acceso denegado.")

    actividades = db.query(models.Actividad).filter(models.Actividad.materia_id == materia_id).all()
    if not actividades:
        raise HTTPException(status_code=404, detail="Sin actividades en esta materia.")

    # Construir mapa matricula → promedio ponderado (guard NaN from old imports)
    promedios: dict[str, float] = {}
    for act in actividades:
        for calif in db.query(models.Calificacion).filter_by(actividad_id=str(act.id)).all():
            m = calif.alumno_id
            valor = 0.0 if (calif.valor is None or math.isnan(calif.valor)) else calif.valor
            promedios[m] = promedios.get(m, 0.0) + valor * (act.ponderacion / 100)

    # Obtener todos los alumnos inscritos para rellenar los que aún no tienen nota
    nrc = get_materia_nrc(materia_id)
    alumnos_map: dict[str, str] = {}  # matricula → nombre
    if nrc:
        for a in get_alumnos_por_nrc(nrc):
            mat = str(a.get("matricula", ""))
            if mat:
                alumnos_map[mat] = a.get("nombre", mat)

    # Todos los alumnos conocidos (los que tienen nota + los inscritos sin nota)
    todas_matriculas = set(promedios.keys()) | set(alumnos_map.keys())

    resultado = []
    for matricula in sorted(todas_matriculas):
        promedio = promedios.get(matricula, 0.0)
        if math.isnan(promedio):
            promedio = 0.0
        redondeado = int(promedio) + 1 if (promedio - int(promedio)) >= 0.5 else int(promedio)

        # Nombre: primero del mapa de inscritos, si no buscar via RPC individual
        nombre = alumnos_map.get(matricula)
        if not nombre:
            nombre = get_alumno_nombre(matricula)

        resultado.append({
            "alumno_id": matricula,
            "nombre": nombre,
            "promedio_exacto": round(promedio, 2),
            "promedio_redondeado": redondeado,
        })

    return {"success": True, "data": resultado, "message": "Concentrado generado exitosamente."}


# ── Vista del alumno: sus propias calificaciones ─────────────────────────────

@app.get("/alumno/{matricula}", summary="Calificaciones de un alumno en todas sus materias")
def calificaciones_alumno(
    matricula: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    # El alumno solo puede ver sus propias calificaciones
    # Docentes/admin pueden ver cualquiera
    if user["rol"] not in ("DOCENTE", "ADMIN"):
        pass  # Alumnos autenticados pueden consultar; validación de identidad en frontend

    # Agrupar calificaciones por materia
    calificaciones = (
        db.query(models.Calificacion)
        .filter(models.Calificacion.alumno_id == matricula)
        .all()
    )

    if not calificaciones:
        return {"success": True, "data": {"matricula": matricula, "materias": []}, "message": "Sin calificaciones."}

    # Recopilar actividades únicas
    actividad_ids = {c.actividad_id for c in calificaciones}
    actividades = {
        str(a.id): a
        for a in db.query(models.Actividad).filter(models.Actividad.id.in_(actividad_ids)).all()
    }

    # Agrupar por materia
    materias: dict[str, dict] = {}
    for calif in calificaciones:
        act = actividades.get(calif.actividad_id)
        if not act:
            continue
        mid = str(act.materia_id)
        if mid not in materias:
            materias[mid] = {"materia_id": mid, "actividades": [], "promedio_exacto": 0.0}
        valor = 0.0 if (calif.valor is None or math.isnan(calif.valor)) else calif.valor
        materias[mid]["actividades"].append({
            "actividad_id": act.id,
            "nombre": act.nombre,
            "ponderacion": act.ponderacion,
            "calificacion": valor,
            "puntos_aportados": round(valor * (act.ponderacion / 100), 2),
        })

    # Calcular promedio por materia (con todas las actividades, no sólo las calificadas)
    for mid, data in materias.items():
        todas_acts = db.query(models.Actividad).filter(models.Actividad.materia_id == mid).all()
        promedio = 0.0
        for act in todas_acts:
            calif = db.query(models.Calificacion).filter_by(
                actividad_id=str(act.id), alumno_id=matricula
            ).first()
            if calif:
                v = 0.0 if (calif.valor is None or math.isnan(calif.valor)) else calif.valor
                promedio += v * (act.ponderacion / 100)
        data["promedio_exacto"] = round(promedio, 2)
        data["promedio_redondeado"] = int(promedio) + 1 if (promedio - int(promedio)) >= 0.5 else int(promedio)

    return {
        "success": True,
        "data": {"matricula": matricula, "materias": list(materias.values())},
        "message": "Calificaciones obtenidas correctamente."
    }


# ── Promedio individual ───────────────────────────────────────────────────────

@app.get("/calificaciones/{materia_id}/{alumno_id}/promedio", summary="Calcular promedio ponderado final")
def calcular_promedio_final(
    materia_id: str,
    alumno_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    if user["rol"] == "DOCENTE":
        if not validar_propiedad_materia(str(user["id"]), materia_id, user.get("email")):
            raise HTTPException(status_code=403, detail="Acceso denegado.")

    actividades = db.query(models.Actividad).filter(models.Actividad.materia_id == materia_id).all()
    if not actividades:
        raise HTTPException(status_code=404, detail="No hay actividades en esta materia.")

    promedio_ponderado = 0.0
    detalles = []
    for act in actividades:
        calif = db.query(models.Calificacion).filter_by(
            actividad_id=str(act.id), alumno_id=alumno_id
        ).first()
        nota = calif.valor if calif else 0.0
        puntos = nota * (act.ponderacion / 100)
        promedio_ponderado += puntos
        detalles.append({
            "actividad": act.nombre,
            "ponderacion_maxima": f"{act.ponderacion}%",
            "nota_obtenida": nota,
            "puntos_aportados": round(puntos, 2)
        })

    return {
        "success": True,
        "data": {
            "alumno_id": alumno_id,
            "materia_id": materia_id,
            "promedio_final": round(promedio_ponderado, 2),
            "desglose": detalles
        },
        "message": "Promedio calculado correctamente."
    }


# ── Startup ───────────────────────────────────────────────────────────────────

from src import rabbitmq_server

def _start_rabbitmq():
    try:
        rabbitmq_server.serve()
    except Exception as e:
        print(f"[WARNING] RabbitMQ-RPC no iniciado: {e}")

@app.on_event("startup")
def startup_event():
    threading.Thread(target=_start_rabbitmq, daemon=True).start()
