from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class ReporteGenerado(Base):
    """
    Historial de cada reporte que se ha generado.
    """
    __tablename__ = "reportes_generados"

    id             = Column(Integer, primary_key=True, index=True)
    materia_id     = Column(String, nullable=False, index=True)   # ID del ms-materias
    docente_id     = Column(String, nullable=True, index=True)    # ID del ms-docentes
    tipo           = Column(String, nullable=False)                # "calificaciones" | "asistencias"
    formato        = Column(String, nullable=False)                # "pdf" | "xls"
    fecha_generado = Column(DateTime(timezone=True), server_default=func.now())


class EstadisticaMateria(Base):
    __tablename__ = "estadisticas_materia"

    id                    = Column(Integer, primary_key=True, index=True)
    materia_id            = Column(String, nullable=False, index=True)
    materia_nombre        = Column(String, nullable=False)
    materia_nrc           = Column(String, nullable=False)
    periodo_nombre        = Column(String, nullable=False)
    docente_id            = Column(String, nullable=False, index=True)
    total_alumnos         = Column(Integer, default=0)
    promedio_general      = Column(Float, default=0.0)
    porcentaje_aprobados  = Column(Float, default=0.0)  # 0-100
    porcentaje_asistencia = Column(Float, default=0.0)  # 0-100
    fecha_registro        = Column(DateTime(timezone=True), server_default=func.now())


class EstadisticaAlumno(Base):
    __tablename__ = "estadisticas_alumno"

    id                      = Column(Integer, primary_key=True, index=True)
    alumno_id               = Column(String, nullable=False, index=True)
    materia_id              = Column(String, nullable=False)
    materia_nombre          = Column(String, nullable=False)
    materia_nrc             = Column(String, nullable=False)
    periodo_nombre          = Column(String, nullable=False)
    porcentaje_asistencia   = Column(Float, default=0.0)   # 0-100
    promedio_calificaciones = Column(Float, default=0.0)   # 0-10
    total_sesiones          = Column(Integer, default=0)
    sesiones_presentes      = Column(Integer, default=0)
    fecha_registro          = Column(DateTime(timezone=True), server_default=func.now())
