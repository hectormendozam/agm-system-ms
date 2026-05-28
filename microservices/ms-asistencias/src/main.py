from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import threading
import uuid
import json
from datetime import datetime

from src.database import engine, Base, get_db, redis_client
from src import rabbitmq_server
from src import models, schemas
from src.rabbitmq_manager import RabbitMQManager
from src.rabbitmq_client import validar_alumno_en_materia
from src.auth_middleware import get_current_user, require_roles

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="MS-5 Asistencias QR",
    description="Gestión de sesiones de 10 min y validación de tokens dinámicos.",
    version="1.0.0"
)

event_publisher = RabbitMQManager()

from starlette.requests import Request as StarletteRequest

@app.middleware("http")
async def strip_service_prefix(request: StarletteRequest, call_next):
    """Gateway adds /asistencias prefix to all paths. Strip it for routes like
    /sesiones/* and /qr/* that don't expect it, but keep /asistencias/* as-is."""
    path = request.scope["path"]
    for sub in ("/sesiones", "/qr", "/estadisticas"):
        if path.startswith(f"/asistencias{sub}"):
            request.scope["path"] = path[len("/asistencias"):]
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
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health check (público, sin auth) ────────────────────────────────────────

@app.get("/")
def read_root():
    return {
        "success": True,
        "data": {"mensaje": "¡MS-5 Asistencias QR en línea!"},
        "message": "Conexión exitosa"
    }


# ── Generar token QR para un alumno ─────────────────────────────────────────
# El alumno llama a este endpoint para obtener su token dinámico

@app.post(
    "/qr/generar",
    summary="Genera un token QR dinámico para el alumno"
)
def generar_token_qr(
    req: schemas.GenerarQRRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Alumno")),
):
    """
    Genera un token único de un solo uso para el alumno.
    El frontend lo convierte en QR para que el docente escanee.
    El token expira junto con la sesión activa (máx 10 min).
    """
    sesion_key = f"sesion_activa:{req.materia_id}"
    if not redis_client.exists(sesion_key):
        raise HTTPException(
            status_code=404,
            detail="No hay sesión activa para esta materia en este momento."
        )

    token = str(uuid.uuid4())
    # Guardamos qué alumno generó este token para validarlo al escanear
    redis_client.setex(f"qr_token:{token}", 600, req.alumno_id)

    return {
        "success": True,
        "data": {"token_qr": token},
        "message": "Token generado. Preséntalo en el QR antes de que expire la sesión."
    }


# ── Docente: iniciar sesión ───────────────────────────────────────────────────

@app.post(
    "/sesiones/iniciar",
    summary="Inicia una sesión de 10 minutos para una materia"
)
def iniciar_sesion(
    req: schemas.IniciarSesionRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    redis_key = f"sesion_activa:{req.materia_id}"

    if redis_client.exists(redis_key):
        raise HTTPException(
            status_code=400,
            detail="Ya existe una sesión activa para esta materia."
        )

    sesion_id = str(uuid.uuid4())
    nueva_sesion = models.SesionAsistencia(
        id=sesion_id,
        materia_id=req.materia_id,
        docente_id=req.docente_id
    )
    db.add(nueva_sesion)
    db.commit()

    sesion_data = {
        "sesion_id": sesion_id,
        "inicio_timestamp": datetime.now().timestamp()
    }
    redis_client.setex(redis_key, 600, json.dumps(sesion_data))

    return {
        "success": True,
        "data": {"sesion_id": sesion_id},
        "message": "Sesión iniciada. Expirará en 10 minutos."
    }


# ── Alumno/Docente: registrar asistencia ─────────────────────────────────────

@app.post(
    "/asistencias/registrar",
    summary="Registra asistencia mediante escaneo de QR"
)
def registrar_asistencia(
    req: schemas.RegistrarAsistenciaRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    # 1. Verificar sesión activa primero
    sesion_key = f"sesion_activa:{req.materia_id}"
    sesion_activa_str = redis_client.get(sesion_key)
    if not sesion_activa_str:
        raise HTTPException(
            status_code=404,
            detail="No hay una sesión activa para esta materia o ya expiró."
        )

    sesion_activa = json.loads(sesion_activa_str)
    tiempo_transcurrido = datetime.now().timestamp() - sesion_activa["inicio_timestamp"]

    if tiempo_transcurrido > 600:
        raise HTTPException(status_code=400, detail="La sesión ha expirado.")

    # 2. Validar anti-replay
    token_key = f"qr_usado:{req.token_qr}"
    if redis_client.exists(token_key):
        raise HTTPException(
            status_code=400,
            detail="Código QR inválido o ya utilizado (Anti-replay)."
        )

    # 2.5 Validar propiedad del QR 
    token_owner = redis_client.get(f"qr_token:{req.token_qr}")

    if not token_owner:
        raise HTTPException(
            status_code=404,
            detail="El token QR proporcionado no existe o ha expirado."
        )

    if token_owner != req.alumno_id:
        raise HTTPException(
            status_code=403,
            detail="Este código QR no pertenece al alumno que intenta registrar la asistencia."
        )

    # 3. Validar inscripción vía RabbitMQ → ms-docentes
    esta_inscrito = validar_alumno_en_materia(req.alumno_id, req.materia_id)
    if not esta_inscrito:
        raise HTTPException(
            status_code=403,
            detail=f"El alumno {req.alumno_id} no está inscrito en la materia {req.materia_id}."
        )

    # 4. Determinar estado según tiempo
    if tiempo_transcurrido <= 300:
        estado = "Presente"
    else:
        estado = "Retardo"

    # 5. Guardar en PostgreSQL
    nuevo_registro = models.RegistroAsistencia(
        sesion_id=sesion_activa["sesion_id"],
        alumno_id=req.alumno_id,
        materia_id=req.materia_id,
        estado=estado
    )
    db.add(nuevo_registro)
    db.commit()

    # 5.5 Publicar evento asíncrono si hay Retardo (Pub/Sub)
    if estado == "Retardo":
        event_publisher.publish_event(
            exchange='events_exchange',
            routing_key='asistencias.retardo',
            message={
                "alumno_id": req.alumno_id,
                "materia_id": req.materia_id,
                "sesion_id": sesion_activa["sesion_id"],
                "timestamp": datetime.now().isoformat()
            }
        )

    # 6. Marcar token como usado (anti-replay)
    redis_client.setex(token_key, 600, "usado")

    # 7. Limpieza: Borrar el token original para liberar memoria de Redis
    redis_client.delete(f"qr_token:{req.token_qr}")

    return {
        "success": True,
        "data": {"estado": estado},
        "message": "Asistencia registrada con éxito."
    }


# ── Docente: cerrar sesión ───────────────────────────────────────────────────

@app.delete(
    "/sesiones/{materia_id}/cerrar",
    summary="Cierra forzosamente una sesión activa"
)
def cerrar_sesion(
    materia_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    sesion_key = f"sesion_activa:{materia_id}"

    if not redis_client.exists(sesion_key):
        raise HTTPException(
            status_code=404,
            detail="No hay una sesión activa para esta materia."
        )

    sesion_data = json.loads(redis_client.get(sesion_key))
    sesion_id = sesion_data["sesion_id"]

    redis_client.delete(sesion_key)

    db_sesion = db.query(models.SesionAsistencia).filter(
        models.SesionAsistencia.id == sesion_id
    ).first()
    if db_sesion:
        db_sesion.activa = False
        db.commit()

    return {
        "success": True,
        "data": {},
        "message": "Sesión cerrada correctamente."
    }


# ── Docente/Admin: consultas ─────────────────────────────────────────────────

@app.get(
    "/asistencias/{materia_id}/hoy",
    summary="Obtiene asistencias de la sesión actual"
)
def asistencias_hoy(
    materia_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    sesion_reciente = db.query(models.SesionAsistencia).filter(
        models.SesionAsistencia.materia_id == materia_id
    ).order_by(models.SesionAsistencia.fecha_creacion.desc()).first()

    if not sesion_reciente:
        return {"success": True, "data": {"registros": []}, "message": "No hay sesiones registradas hoy."}

    registros = db.query(models.RegistroAsistencia).filter(
        models.RegistroAsistencia.sesion_id == sesion_reciente.id
    ).all()

    # Enriquecer los datos llamando a ms-docentes por RabbitMQ
    from src.rabbitmq_manager import RabbitMQRpcClient
    rpc_client = RabbitMQRpcClient()
    resultados = []

    for r in registros:
        nombre = f"Alumno {r.alumno_id}"
        matricula = "-"
        try:
            # Consultamos el nombre y matrícula reales
            resp = rpc_client.call('rpc_docentes_queue', 'get_alumno_by_id', {"id": r.alumno_id})
            if resp and resp.get("success"):
                nombre = resp["data"].get("nombre", nombre)
                # Si falla, veremos este texto en lugar de un guion mudo
                matricula = resp["data"].get("matricula", "No recibida")
        except Exception:
            pass

        # Construimos el JSON exacto asegurando todas las posibles llaves de Angular
        resultados.append({
            "alumno_id": r.alumno_id,
            "alumno_nombre": nombre,
            "nombre": nombre,
            "alumno_matricula": matricula,
            "matricula": matricula,
            "timestamp": r.hora_registro.isoformat() if r.hora_registro else "",
            "hora": r.hora_registro.isoformat() if r.hora_registro else "",
            "estado": r.estado
        })

    return {
        "success": True,
        "data": {
            "sesion_id": sesion_reciente.id,
            "fecha": sesion_reciente.fecha_creacion,
            "registros": resultados
        },
        "message": "Asistencias de la sesión reciente obtenidas."
    }


@app.get(
    "/asistencias/{materia_id}/historial",
    summary="Historial paginado de sesiones de una materia"
)
def historial_asistencias(
    materia_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("Docente", "Administrador")),
):
    offset = (page - 1) * limit

    total_sesiones = db.query(models.SesionAsistencia).filter(
        models.SesionAsistencia.materia_id == materia_id
    ).count()

    sesiones = db.query(models.SesionAsistencia).filter(
        models.SesionAsistencia.materia_id == materia_id
    ).order_by(models.SesionAsistencia.fecha_creacion.desc()).offset(offset).limit(limit).all()

    return {
        "success": True,
        "data": {
            "total_records": total_sesiones,
            "current_page": page,
            "limit": limit,
            "total_pages": (total_sesiones + limit - 1) // limit,
            "sesiones": sesiones
        },
        "message": "Historial paginado obtenido correctamente."
    }


# ── Startup ──────────────────────────────────────────────────────────────────

def _start_rabbitmq():
    try:
        rabbitmq_server.serve()
    except Exception as e:
        print(f"[WARNING] No se pudo iniciar el servidor RabbitMQ-RPC: {e}")


@app.on_event("startup")
def startup_event():
    rb_thread = threading.Thread(target=_start_rabbitmq, daemon=True)
    rb_thread.start()