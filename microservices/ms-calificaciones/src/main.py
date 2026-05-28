from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import threading
import pandas as pd
import io
import sys
import os

from src.database import engine, Base, get_db
from src import models, schemas
from src.auth_middleware import get_current_user, require_roles
from src.rabbitmq_client import validar_propiedad_materia

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="MS-4 Calificaciones",
    description="Gestión de actividades, notas por Excel y promedios ponderados.",
    version="1.0.0"
)

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

@app.post("/actividades", summary="Crear una nueva actividad evaluativa")
def crear_actividad(
    actividad: schemas.ActividadCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    if user["rol"] == "Docente":
        es_su_materia = validar_propiedad_materia(str(user["id"]), actividad.materia_id, user.get("email"))
        if not es_su_materia:
            raise HTTPException(
                status_code=403,
                detail="Acceso denegado. No estás asignado a esta materia."
            )

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

@app.get("/actividades/{materia_id}", summary="Listar actividades de una materia")
def listar_actividades(
    materia_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    # --- Candado Anti-IDOR para lectura ---
    if user["rol"] == "Docente":
        es_su_materia = validar_propiedad_materia(str(user["id"]), materia_id, user.get("email"))
        if not es_su_materia:
            raise HTTPException(
                status_code=403,
                detail="Acceso denegado. No puedes ver la información de una materia ajena."
            )
    # --------------------------------------

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

@app.post("/calificaciones", summary="Registrar calificación individual")
def registrar_calificacion(
    calif: schemas.CalificacionCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    actividad = db.query(models.Actividad).filter(models.Actividad.id == calif.actividad_id).first()
    if not actividad:
        raise HTTPException(status_code=404, detail="Actividad no encontrada.")

    if user["rol"] == "Docente":
        es_su_materia = validar_propiedad_materia(str(user["id"]), str(actividad.materia_id), user.get("email"))
        if not es_su_materia:
            raise HTTPException(
                status_code=403,
                detail="Acceso denegado. No estás asignado a esta materia."
            )

    calificacion_existente = db.query(models.Calificacion).filter_by(
        actividad_id=calif.actividad_id, alumno_id=calif.alumno_id
    ).first()

    if calificacion_existente:
        calificacion_existente.valor = calif.valor
    else:
        nueva_calif = models.Calificacion(
            actividad_id=calif.actividad_id,
            alumno_id=calif.alumno_id,
            valor=calif.valor
        )
        db.add(nueva_calif)

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

    if user["rol"] == "Docente":
        es_su_materia = validar_propiedad_materia(str(user["id"]), str(actividad.materia_id), user.get("email"))
        if not es_su_materia:
            raise HTTPException(
                status_code=403,
                detail="Acceso denegado. No estás asignado a esta materia."
            )

    if not file.filename.endswith(('.xls', '.xlsx')):
        raise HTTPException(status_code=400, detail="El archivo debe ser un Excel (.xlsx)")

    contents = await file.read()
    try:
        # Intentar leer el Excel de forma flexible
        # Primero leemos todo sin asumir encabezados
        df_raw = pd.read_excel(io.BytesIO(contents), header=None)
        
        # Buscar la fila que contiene los encabezados reales
        header_row_index = 0
        found_headers = False
        target_cols = ['matricula', 'calificacion', 'puntos', 'dirección de correo', 'correo', 'email']
        
        for i, row in df_raw.iterrows():
            row_str = [str(val).lower().strip() for val in row if val is not None]
            if any(col in row_str for col in target_cols):
                header_row_index = i
                found_headers = True
                break
        
        if found_headers:
            df = pd.read_excel(io.BytesIO(contents), header=header_row_index)
        else:
            df = pd.read_excel(io.BytesIO(contents))
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al leer el Excel. Revisa el formato: {str(e)}")

    df.columns = df.columns.str.lower().str.strip()
    
    # Mapeo flexible de columnas
    col_matricula = None
    for col in ['matricula', 'dirección de correo', 'correo', 'email']:
        if col in df.columns:
            col_matricula = col
            break
            
    col_calificacion = None
    for col in ['calificacion', 'puntos', 'nota', 'puntuación']:
        if col in df.columns:
            col_calificacion = col
            break

    if not col_matricula or not col_calificacion:
        raise HTTPException(
            status_code=400, 
            detail=f"No se encontraron las columnas necesarias. Columnas detectadas: {list(df.columns)}. Se requiere algo similar a 'matricula' y 'calificacion' o 'puntos'."
        )

    registros = 0
    for index, row in df.iterrows():
        raw_matricula = str(row[col_matricula]).strip()
        
        # Si es un correo, extraer la matricula (ej: bb202321840@alm.buap.mx -> 202321840)
        # Algunos correos institucionales de la BUAP tienen prefijos de 2 letras
        matricula = raw_matricula
        if "@" in raw_matricula:
            username = raw_matricula.split("@")[0]
            # Quitar prefijos no numéricos (ej: bb2022 -> 2022)
            import re
            match = re.search(r'\d+', username)
            if match:
                matricula = match.group()
            else:
                matricula = username
        
        if matricula.endswith('.0'):
            matricula = matricula[:-2]

        try:
            valor_nota = float(row[col_calificacion])
        except (ValueError, TypeError):
            continue # Saltar filas sin nota válida

        calificacion_existente = db.query(models.Calificacion).filter_by(
            actividad_id=actividad_id, alumno_id=matricula
        ).first()

        if calificacion_existente:
            calificacion_existente.valor = valor_nota
        else:
            nueva_calif = models.Calificacion(
                actividad_id=actividad_id, alumno_id=matricula, valor=valor_nota
            )
            db.add(nueva_calif)
        registros += 1

    db.commit()

    return {
        "success": True,
        "data": {"registros_procesados": registros},
        "message": f"Se procesaron {registros} calificaciones correctamente para la actividad '{actividad.nombre}'."
    }

@app.get("/calificaciones/{materia_id}/{alumno_id}/promedio", summary="Calcular promedio ponderado final")
def calcular_promedio_final(
    materia_id: str,
    alumno_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    if user["rol"] == "Docente":
        es_su_materia = validar_propiedad_materia(str(user["id"]), materia_id, user.get("email"))
        if not es_su_materia:
            raise HTTPException(
                status_code=403,
                detail="Acceso denegado. No puedes ver la información de una materia ajena."
            )

    materia_id = materia_id.strip()
    alumno_id = alumno_id.strip()
    
    actividades = db.query(models.Actividad).filter(models.Actividad.materia_id == materia_id).all()
    
    if not actividades:
        raise HTTPException(status_code=404, detail="No hay actividades registradas en esta materia.")

    promedio_ponderado = 0.0
    detalles = []

    for act in actividades:
        calif = db.query(models.Calificacion).filter_by(
            actividad_id=str(act.id), alumno_id=alumno_id
        ).first()

        nota = calif.valor if calif else 0.0
        puntos_ganados = nota * (act.ponderacion / 100)
        promedio_ponderado += puntos_ganados
        
        detalles.append({
            "actividad": act.nombre,
            "ponderacion_maxima": f"{act.ponderacion}%",
            "nota_obtenida": nota,
            "puntos_aportados": round(puntos_ganados, 2)
        })

    promedio_final = round(promedio_ponderado, 2)

    return {
        "success": True,
        "data": {
            "alumno_id": alumno_id,
            "materia_id": materia_id,
            "promedio_final": promedio_final,
            "desglose": detalles
        },
        "message": "Promedio calculado correctamente."
    }

@app.get("/ponderaciones/{materia_id}", summary="Obtener ponderaciones de una materia")
def obtener_ponderaciones(
    materia_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    if user["rol"] == "Docente":
        es_su_materia = validar_propiedad_materia(str(user["id"]), materia_id, user.get("email"))
        if not es_su_materia:
            raise HTTPException(
                status_code=403,
                detail="Acceso denegado. No puedes ver la información de una materia ajena."
            )

    actividades = db.query(models.Actividad).filter(models.Actividad.materia_id == materia_id).all()
    total = sum(act.ponderacion for act in actividades)
    return {"success": True, "data": {"materia_id": materia_id, "total_ponderacion": total, "detalles": actividades}}


@app.post("/ponderaciones/{materia_id}", summary="Configurar ponderaciones de una materia")
def crear_ponderaciones(
    materia_id: str,
    payload: schemas.PonderacionesCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    if user["rol"] == "Docente":
        es_su_materia = validar_propiedad_materia(str(user["id"]), materia_id, user.get("email"))
        if not es_su_materia:
            raise HTTPException(
                status_code=403,
                detail="Acceso denegado. No estás asignado a esta materia."
            )

    if not payload.ponderaciones:
        raise HTTPException(status_code=400, detail="Debe enviar al menos una ponderación.")

    total_nuevo = sum(item.ponderacion for item in payload.ponderaciones)
    if total_nuevo <= 0 or total_nuevo > 100:
        raise HTTPException(status_code=400, detail="La suma de las ponderaciones debe estar entre 1 y 100.")

    actividades_existentes = db.query(models.Actividad).filter(models.Actividad.materia_id == materia_id).all()
    suma_existente = sum(act.ponderacion for act in actividades_existentes)

    if actividades_existentes and suma_existente != 0:
        raise HTTPException(
            status_code=400,
            detail=f"La materia ya tiene ponderaciones registradas con un total de {suma_existente}%. Use PUT para actualizar o elimine las anteriores antes de volver a configurar."
        )

    if round(total_nuevo, 2) != 100.00:
        raise HTTPException(status_code=400, detail=f"La suma de las ponderaciones debe ser exactamente 100%. Actualmente suma {total_nuevo}%.")

    creadas = []
    for item in payload.ponderaciones:
        if item.ponderacion <= 0 or item.ponderacion > 100:
            raise HTTPException(status_code=400, detail="Cada ponderación debe estar entre 1 y 100.")

        nueva_actividad = models.Actividad(
            materia_id=materia_id,
            nombre=item.nombre,
            ponderacion=item.ponderacion,
        )
        db.add(nueva_actividad)
        creadas.append(nueva_actividad)

    db.commit()

    for actividad in creadas:
        db.refresh(actividad)

    return {
        "success": True,
        "data": {
            "materia_id": materia_id,
            "total_ponderacion": 100.0,
            "ponderaciones_creadas": [
                {"actividad_id": actividad.id, "nombre": actividad.nombre, "ponderacion": actividad.ponderacion}
                for actividad in creadas
            ],
        },
        "message": "Ponderaciones configuradas correctamente."
    }

@app.put("/ponderaciones/{actividad_id}", summary="Actualizar ponderación de una actividad")
def actualizar_ponderacion(
    actividad_id: str,
    nueva_ponderacion: float,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    if nueva_ponderacion <= 0 or nueva_ponderacion > 100:
        raise HTTPException(status_code=400, detail="Ponderación inválida.")
        
    actividad = db.query(models.Actividad).filter(models.Actividad.id == actividad_id).first()
    if not actividad:
        raise HTTPException(status_code=404, detail="Actividad no encontrada.")

    if user["rol"] == "Docente":
        es_su_materia = validar_propiedad_materia(str(user["id"]), str(actividad.materia_id), user.get("email"))
        if not es_su_materia:
            raise HTTPException(
                status_code=403,
                detail="Acceso denegado. No estás asignado a esta materia."
            )

    otras_actividades = db.query(models.Actividad).filter(
        models.Actividad.materia_id == actividad.materia_id,
        models.Actividad.id != actividad_id
    ).all()
    suma_otras = sum(act.ponderacion for act in otras_actividades)

    if suma_otras + nueva_ponderacion > 100:
        raise HTTPException(
            status_code=400,
            detail=f"Excede el 100%. Las demás actividades suman {suma_otras}%. El máximo para esta es {100 - suma_otras}%."
        )
        
    actividad.ponderacion = nueva_ponderacion
    db.commit()
    return {"success": True, "message": "Ponderación actualizada."}

@app.get("/concentrado/{materia_id}", summary="Obtener el concentrado final de calificaciones")
def obtener_concentrado(
    materia_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    if user["rol"] == "Docente":
        es_su_materia = validar_propiedad_materia(str(user["id"]), materia_id, user.get("email"))
        if not es_su_materia:
            raise HTTPException(
                status_code=403,
                detail="Acceso denegado. No puedes ver la información de una materia ajena."
            )

    actividades = db.query(models.Actividad).filter(models.Actividad.materia_id == materia_id).all()
    if not actividades:
        raise HTTPException(status_code=404, detail="Sin actividades en esta materia.")
    
    concentrado_alumnos = {}
    
    for act in actividades:
        calificaciones = db.query(models.Calificacion).filter_by(actividad_id=str(act.id)).all()
        for calif in calificaciones:
            matricula = calif.alumno_id
            puntos = calif.valor * (act.ponderacion / 100)
            
            if matricula not in concentrado_alumnos:
                concentrado_alumnos[matricula] = 0.0
            concentrado_alumnos[matricula] += puntos
            
    resultado = []
    for matricula, promedio in concentrado_alumnos.items():
        redondeado = int(promedio) + 1 if (promedio - int(promedio)) >= 0.5 else int(promedio)
        resultado.append({
            "alumno_id": matricula,
            "promedio_exacto": round(promedio, 2),
            "promedio_redondeado": redondeado
        })
        
    return {"success": True, "data": resultado, "message": "Concentrado generado exitosamente."}


from src import rabbitmq_server

def _start_rabbitmq():
    try:
        rabbitmq_server.serve()
    except Exception as e:
        print(f"[WARNING] No se pudo iniciar el servidor RabbitMQ-RPC: {e}")

@app.on_event("startup")
def startup_event():
    threading.Thread(target=_start_rabbitmq, daemon=True).start()
    print("[Startup] Servidor RabbitMQ-RPC iniciado en hilo daemon")