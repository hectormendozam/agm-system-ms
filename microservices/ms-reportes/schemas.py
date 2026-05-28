from pydantic import BaseModel, field_validator
from typing import List, Optional
from datetime import datetime


# ── Estadísticas de Materia (docente) ─────────────────────────────────────────

class EstadisticaMateriaCreate(BaseModel):
    materia_id:            str
    materia_nombre:        str
    materia_nrc:           str
    periodo_nombre:        str
    docente_id:            str
    total_alumnos:         int
    promedio_general:      float
    porcentaje_aprobados:  float
    porcentaje_asistencia: float = 0.0


class EstadisticaMateriaResponse(BaseModel):
    id:                    int
    materia_id:            str
    materia_nombre:        str
    materia_nrc:           str
    periodo_nombre:        str
    docente_id:            str
    total_alumnos:         int
    promedio_general:      float
    porcentaje_aprobados:  float
    porcentaje_asistencia: float = 0.0
    fecha_registro:        datetime

    class Config:
        from_attributes = True


# ── Estadísticas de Alumno ────────────────────────────────────────────────────

class EstadisticaAlumnoCreate(BaseModel):
    alumno_id:               str
    materia_id:              str
    materia_nombre:          str
    materia_nrc:             str
    periodo_nombre:          str
    porcentaje_asistencia:   float
    promedio_calificaciones: float
    total_sesiones:          int
    sesiones_presentes:      int

    @field_validator("porcentaje_asistencia", "promedio_calificaciones")
    @classmethod
    def rango_valido(cls, v: float) -> float:
        if not (0 <= v <= 100):
            raise ValueError("El valor debe estar entre 0 y 100")
        return v


class EstadisticaAlumnoResponse(BaseModel):
    id:                      int
    alumno_id:               str
    materia_id:              str
    materia_nombre:          str
    materia_nrc:             str
    periodo_nombre:          str
    porcentaje_asistencia:   float
    promedio_calificaciones: float
    total_sesiones:          int
    sesiones_presentes:      int
    fecha_registro:          datetime

    class Config:
        from_attributes = True


# ── Reportes (historial) ──────────────────────────────────────────────────────

class ReporteGeneradoResponse(BaseModel):
    id:             int
    materia_id:     str
    docente_id:     Optional[str]
    tipo:           str
    formato:        str
    fecha_generado: datetime

    class Config:
        from_attributes = True


# ── Body Pydantic para POST /reportes (datos reales) ─────────────────────────

class AlumnoCalificacionBody(BaseModel):
    matricula:         str
    nombre:            str
    promedio_real:     float = 0.0
    calificacion_final: float = 0.0


class DatosCalificacionesReporte(BaseModel):
    materia_nombre: str = ""
    materia_nrc:    str = ""
    periodo:        str = ""
    docente:        str = ""
    docente_id:     Optional[str] = None
    alumnos:        List[AlumnoCalificacionBody] = []


class AlumnoAsistenciaBody(BaseModel):
    matricula: str
    nombre:    str
    estado:    str = "Presente"   # Presente | Retardo | Falta
    hora:      str = ""


class SesionAsistenciaBody(BaseModel):
    fecha:    str
    alumnos:  List[AlumnoAsistenciaBody] = []


class DatosAsistenciasReporte(BaseModel):
    materia_nombre: str = ""
    materia_nrc:    str = ""
    periodo:        str = ""
    docente_id:     Optional[str] = None
    sesiones:       List[SesionAsistenciaBody] = []


# ── Respuestas genéricas ──────────────────────────────────────────────────────

class RespuestaBase(BaseModel):
    success: bool
    message: str


class RespuestaEstadistica(RespuestaBase):
    data: Optional[EstadisticaMateriaResponse] = None


class RespuestaEstadisticaAlumno(RespuestaBase):
    data: Optional[EstadisticaAlumnoResponse] = None


class RespuestaReporte(RespuestaBase):
    data: Optional[ReporteGeneradoResponse] = None


# ── Respuestas paginadas ──────────────────────────────────────────────────────

class PaginaEstadisticasMateria(BaseModel):
    total: int
    page:  int
    limit: int
    items: List[EstadisticaMateriaResponse]


class RespuestaPaginadaEstadisticasMateria(RespuestaBase):
    data: Optional[PaginaEstadisticasMateria] = None


class PaginaEstadisticasAlumno(BaseModel):
    total: int
    page:  int
    limit: int
    items: List[EstadisticaAlumnoResponse]


class RespuestaPaginadaEstadisticasAlumno(RespuestaBase):
    data: Optional[PaginaEstadisticasAlumno] = None
