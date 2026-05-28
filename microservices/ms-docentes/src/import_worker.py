"""
import_worker.py
Consume la cola `docentes_import_jobs_queue` y procesa en un hilo separado
la creación de usuarios en ms-auth + notificaciones por cada registro importado.

El callback de pika hace ACK inmediatamente y delega el trabajo a un thread,
evitando que el consumer connection pierda el heartbeat en imports grandes.
"""
import json
import logging
import os
import sys
import threading
import time
import secrets
import string

import pika

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import SessionLocal
import models
from rabbitmq_manager import RabbitMQRpcClient, RabbitMQManager

logger = logging.getLogger("[ImportWorker]")
QUEUE_NAME = "docentes_import_jobs_queue"


# ── Helpers de notificación ───────────────────────────────────────────────────

def _generar_password(length=8) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for i in range(length))


def _create_user(rpc: RabbitMQRpcClient, email: str, rol: str) -> dict:
    password = f"AGM-{_generar_password()}"
    try:
        res = rpc.call("rpc_auth_queue", "create_user", {
            "email": email, 
            "password": password, 
            "rol": rol
        })
        if res.get("success"):
            res["password"] = password  # Devolvemos la clave en claro para la notificación
        return res
    except Exception as e:
        logger.error(f"RPC create_user falló para {email}: {e}")
        return {"success": False, "error_message": str(e)}


def _notify_docente(pub: RabbitMQManager, docente: dict, password: str, token: str):
    try:
        pub.publish_event(
            exchange="events_exchange",
            routing_key="docentes.bienvenida",
            message={
                "docenteId": str(docente["id"]),
                "docenteNombre": docente["nombre"],
                "docenteEmail": docente["email"],
                "claveUnica": password,
                "auth_token": token,
            },
        )
    except Exception as e:
        logger.error(f"Error notificando docente {docente['email']}: {e}")


def _notify_alumno(pub: RabbitMQManager, alumno: dict, materia_nombre: str, password: str, token: str):
    try:
        pub.publish_event(
            exchange="events_exchange",
            routing_key="periodos.bienvenida",
            message={
                "alumnoId": str(alumno["id"]),
                "alumnoNombre": alumno["nombre"],
                "alumnoEmail": alumno["email"],
                "materiaNombre": materia_nombre,
                "claveUnica": password,
                "auth_token": token,
            },
        )
    except Exception as e:
        logger.error(f"Error notificando alumno {alumno['email']}: {e}")


# ── Procesadores (se ejecutan en hilos propios con conexiones propias) ────────

def _procesar_docentes(data: dict):
    docente_ids: list = data.get("docente_ids", [])
    token: str = data.get("token", "no-token")
    whitelist: list = data.get("whitelist", [])

    rpc = RabbitMQRpcClient()
    pub = RabbitMQManager()
    db = SessionLocal()
    try:
        ok = skipped = errors = 0
        for doc_id in docente_ids:
            docente = db.query(models.Docente).filter(models.Docente.id == doc_id).first()
            if not docente or not docente.email:
                skipped += 1
                continue

            res = _create_user(rpc, docente.email, "Docente")
            
            msg = res.get("error_message") or res.get("message") or ""
            ya_registrado = "ya esta registrado" in msg.lower() or "already registered" in msg.lower()

            if not res.get("success") and not ya_registrado:
                logger.warning(f"No se creó usuario para {docente.email}: {msg}")
                errors += 1
                continue

            ok += 1
            if not whitelist or docente.email.lower() in whitelist:
                password = res.get("password") if res.get("success") else "Ya registrado"
                _notify_docente(
                    pub,
                    {"id": docente.id, "nombre": docente.nombre, "email": docente.email},
                    password,
                    token,
                )
            else:
                logger.info(f"Notificación omitida (whitelist): {docente.email}")

        logger.info(f"Job docentes terminado — creados:{ok} sin_email:{skipped} errores:{errors}")
    except Exception as e:
        logger.error(f"Error en job docentes: {e}")
    finally:
        db.close()


def _procesar_alumnos(data: dict):
    alumno_ids: list = data.get("alumno_ids", [])
    token: str = data.get("token", "no-token")
    whitelist: list = data.get("whitelist", [])
    materia_nombre: str = data.get("materia_nombre", "")

    rpc = RabbitMQRpcClient()
    pub = RabbitMQManager()
    db = SessionLocal()
    try:
        ok = skipped = errors = 0
        for alu_id in alumno_ids:
            alumno = db.query(models.Alumno).filter(models.Alumno.id == alu_id).first()
            if not alumno or not alumno.email:
                skipped += 1
                continue

            res = _create_user(rpc, alumno.email, "Alumno")
            if not res.get("success"):
                msg = res.get("error_message") or res.get("message") or "Error desconocido"
                logger.warning(f"No se creó usuario para {alumno.email}: {msg}")
                errors += 1
                continue

            ok += 1
            if not whitelist or alumno.email.lower() in whitelist:
                _notify_alumno(
                    pub,
                    {
                        "id": alumno.id,
                        "nombre": alumno.nombre,
                        "email": alumno.email,
                        "matricula": alumno.matricula,
                    },
                    materia_nombre,
                    res["password"],
                    token,
                )
            else:
                logger.info(f"Notificación omitida (whitelist): {alumno.email}")

        logger.info(f"Job alumnos terminado — creados:{ok} sin_email:{skipped} errores:{errors}")
    except Exception as e:
        logger.error(f"Error en job alumnos: {e}")
    finally:
        db.close()


# ── Dispatcher: ACK inmediato + hilo separado ─────────────────────────────────

def _dispatch(data: dict):
    job_type = data.get("job_type")
    if job_type == "crear_usuarios_docentes":
        t = threading.Thread(target=_procesar_docentes, args=(data,), daemon=True)
    elif job_type == "crear_usuarios_alumnos":
        t = threading.Thread(target=_procesar_alumnos, args=(data,), daemon=True)
    else:
        logger.warning(f"Tipo de job desconocido: {job_type}")
        return
    t.start()


def _on_message(ch, method, _properties, body):
    try:
        data = json.loads(body)
        logger.info(f"Job recibido: {data.get('job_type')} — ACK inmediato, procesando en hilo")
        ch.basic_ack(delivery_tag=method.delivery_tag)
        _dispatch(data)
    except Exception as e:
        logger.error(f"Error en callback: {e}")
        ch.basic_ack(delivery_tag=method.delivery_tag)


# ── Bucle principal con reconexión ────────────────────────────────────────────

def serve():
    url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672")
    logger.info("ImportWorker iniciando…")

    while True:
        try:
            params = pika.URLParameters(url)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=QUEUE_NAME, on_message_callback=_on_message)
            logger.info(f"Consumiendo cola '{QUEUE_NAME}'")
            channel.start_consuming()
        except Exception as e:
            logger.error(f"Conexión perdida, reintentando en 5s: {e}")
            time.sleep(5)
