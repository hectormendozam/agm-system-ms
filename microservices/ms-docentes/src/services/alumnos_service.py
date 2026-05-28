"""
services/alumnos_service.py
Lógica de negocio para importación, consulta y baja de alumnos.
"""
import pdfplumber
import re
import secrets
import string
from io import BytesIO
from typing import List
from sqlalchemy.orm import Session
from fastapi import HTTPException

import models
from rabbitmq_manager import RabbitMQRpcClient


def _generar_clave_unica(length=8) -> str:
    """Genera una contraseña aleatoria segura."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for i in range(length))


def _extraer_nrc_desde_pdf(contenido: bytes) -> str | None:
    with pdfplumber.open(BytesIO(contenido)) as pdf:
        for pagina in pdf.pages:
            text = pagina.extract_text() or ""
            nrc_match = re.search(r'NRC:\s*(\d+)', text)
            if nrc_match:
                return nrc_match.group(1)
    return None


def _normalizar_mailto(uri: str | None) -> str | None:
    if not uri:
        return None
    uri = uri.strip()
    if not uri.lower().startswith("mailto:"):
        return None

    email = uri[len("mailto:"):].strip()
    if not email or email.startswith("?"):
        return None
    email = email.split("?", 1)[0].strip()
    return email if re.fullmatch(r"[\w.+-]+@[\w.-]+\.\w+", email) else None


def _extraer_correos_alumnos_desde_pdf(contenido: bytes) -> List[str]:
    correos: List[str] = []
    vistos = set()

    with pdfplumber.open(BytesIO(contenido)) as pdf:
        for pagina in pdf.pages:
            for annot in getattr(pagina, "annots", []) or []:
                email = _normalizar_mailto(annot.get("uri"))
                if email and email not in vistos:
                    vistos.add(email)
                    correos.append(email)

    return correos


def importar_alumnos_desde_pdf(contenido: bytes, expected_nrc: str, db: Session) -> List[dict]:
    """
    Lee un archivo PDF con la lista de alumnos inscritos en un NRC.
    Retorna lista de diccionarios con info del alumno y su clave generada.
    """
    alumnos_procesados = []
    rpc_client = RabbitMQRpcClient()
    correos = _extraer_correos_alumnos_desde_pdf(contenido)
    alumno_index = 0

    with pdfplumber.open(BytesIO(contenido)) as pdf:
        current_nrc = None

        for pagina in pdf.pages:
            text = pagina.extract_text()
            if not text:
                continue

            # Extraer NRC del encabezado
            nrc_match = re.search(r'NRC:\s*(\d+)', text)
            if nrc_match:
                current_nrc = nrc_match.group(1)

            nrc_to_use = current_nrc if current_nrc else expected_nrc

            lines = text.split('\n')
            last_student = None

            for line in lines:
                line_str = line.strip()
                if not line_str:
                    continue

                # Línea de alumno: <num> <NOMBRE> <matricula-9-digits> **Inscrito por Web** ...
                match = re.search(
                    r'^(\d+)\s+(.*?)\s+(\d{9})\s+\*\*Inscrito por Web\*\*\s+(.+?)\s+([\d\.]+)',
                    line_str
                )
                if match:
                    numero_registro = int(match.group(1))
                    nombre = match.group(2).strip()
                    matricula = match.group(3).strip()
                    
                    # Usar el correo extraído de los hipervínculos si está disponible
                    email = correos[alumno_index] if alumno_index < len(correos) else f"{matricula}@alumno.buap.mx"
                    alumno_index += 1

                    # Generar clave única para ms-auth
                    clave = f"AGM-{_generar_clave_unica()}"

                    alumno = (
                        db.query(models.Alumno)
                        .filter(
                            models.Alumno.matricula == matricula,
                            models.Alumno.nrc == nrc_to_use,
                        )
                        .first()
                    )
                    
                    es_nuevo = False
                    if not alumno:
                        alumno = models.Alumno(
                            numero_registro=numero_registro,
                            matricula=matricula,
                            nombre=nombre,
                            email=email,
                            nrc=nrc_to_use,
                            activo=True,
                        )
                        db.add(alumno)
                        es_nuevo = True
                    else:
                        alumno.numero_registro = numero_registro
                        alumno.nombre = nombre
                        alumno.email = email
                        alumno.activo = True
                    
                    db.flush()

                    alumnos_procesados.append({
                        "alumno": alumno,
                        "es_nuevo": es_nuevo
                    })

                    last_student = alumno

                elif last_student:
                    if (
                        not re.match(r'^\d+', line_str)
                        and 'Clase' not in line_str
                        and 'Página' not in line_str
                        and 'Regresar' not in line_str
                        and '©' not in line_str
                        and 'VERSIÓN' not in line_str
                        and re.match(r'^[A-ZÁÉÍÓÚÑÜ\s\.,]+$', line_str)
                    ):
                        last_student.nombre += " " + line_str
                        if alumnos_procesados:
                            alumnos_procesados[-1]["alumno"].nombre = last_student.nombre

    db.commit()
    return alumnos_procesados


def listar_alumnos_por_materia(nrc: str, db: Session) -> List[models.Alumno]:
    """Retorna sólo alumnos ACTIVOS de un NRC."""
    return (
        db.query(models.Alumno)
        .filter(models.Alumno.nrc == nrc, models.Alumno.activo == True)
        .all()
    )


def listar_alumnos(db: Session, search: str | None = None) -> List[models.Alumno]:
    query = db.query(models.Alumno).filter(models.Alumno.activo == True)
    if search:
        like = f"%{search}%"
        query = query.filter(
            (models.Alumno.matricula.ilike(like))
            | (models.Alumno.nombre.ilike(like))
            | (models.Alumno.email.ilike(like))
        )
    return query.order_by(models.Alumno.nrc, models.Alumno.numero_registro, models.Alumno.nombre).all()


def dar_de_baja(alumno_id: int, db: Session) -> models.Alumno:
    """
    Baja lógica: marca el campo activo=False.
    No se elimina el registro para conservar historial.
    """
    alumno = db.query(models.Alumno).filter(models.Alumno.id == alumno_id).first()
    if not alumno:
        raise HTTPException(status_code=404, detail=f"Alumno {alumno_id} no encontrado")
    if not alumno.activo:
        raise HTTPException(status_code=409, detail="El alumno ya está dado de baja")

    alumno.activo = False
    db.commit()
    db.refresh(alumno)
    return alumno
