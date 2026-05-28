"""
schemas.py - Contratos de datos (Pydantic) para el MS-3: Docentes & Alumnos.
"""
from pydantic import BaseModel
from typing import Optional, List


class MateriaDocenteResponse(BaseModel):
    id: int
    nrc: str
    nombre_materia: str
    seccion: Optional[str] = None
    clave: Optional[str] = None
    horario: Optional[str] = None

    class Config:
        from_attributes = True


class DocenteResponse(BaseModel):
    id: int
    nombre: str
    apellido: Optional[str] = None
    email: Optional[str] = None
    clave_empleado: Optional[str] = None
    departamento: Optional[str] = None
    activo: bool = True
    materias: List[MateriaDocenteResponse] = []

    class Config:
        from_attributes = True


class ImportacionResponse(BaseModel):
    """Respuesta generica para operaciones de importacion."""
    mensaje: str
    registros_importados: int
    cuentas_creadas: int = 0
    cuentas_existentes: int = 0
    cuentas_fallidas: int = 0


class AlumnoResponse(BaseModel):
    id: int
    numero_registro: Optional[int] = None
    matricula: str
    nombre: str
    apellido: Optional[str] = None
    email: Optional[str] = None
    nrc: str
    activo: bool

    class Config:
        from_attributes = True


class BajaResponse(BaseModel):
    """Confirmacion de baja de materia."""
    mensaje: str
    alumno_id: int
    nrc: str


class BajaDocenteResponse(BaseModel):
    """Confirmacion de baja logica de docente."""
    mensaje: str
    docente_id: int
