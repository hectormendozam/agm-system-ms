from django.core.exceptions import ValidationError
from django.db import models, transaction


class Periodo(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    plan_estudios = models.CharField(max_length=180)
    activo = models.BooleanField(default=False)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-activo", "-fecha_inicio", "nombre"]

    def clean(self):
        if self.fecha_inicio and self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValidationError({"fecha_fin": "La fecha de fin debe ser mayor o igual a la fecha de inicio."})

    def save(self, *args, **kwargs):
        self.full_clean()
        with transaction.atomic():
            if self.activo:
                Periodo.objects.exclude(pk=self.pk).filter(activo=True).update(activo=False)
            super().save(*args, **kwargs)

    def __str__(self):
        estado = "Activo" if self.activo else "Inactivo"
        return f"{self.nombre} ({estado})"


class Materia(models.Model):
    nrc = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=160)
    creditos = models.PositiveSmallIntegerField(default=0)
    seccion = models.CharField(max_length=20)
    clave = models.CharField(max_length=40, blank=True, default="")
    docente_id = models.PositiveIntegerField(null=True, blank=True, default=None)
    docente_nombre = models.CharField(max_length=160, blank=True, default="")
    horario = models.CharField(max_length=120, blank=True, default="")
    periodo_id = models.PositiveIntegerField()
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creado_en", "nombre"]
        indexes = [
            models.Index(fields=["nrc"]),
            models.Index(fields=["periodo_id"]),
            models.Index(fields=["docente_id"]),
        ]

    def clean(self):
        if not self.nrc.strip():
            raise ValidationError({"nrc": "El NRC no puede estar vacío."})
        if not self.nombre.strip():
            raise ValidationError({"nombre": "El nombre de la materia no puede estar vacío."})
        if self.creditos in (None, ""):
            self.creditos = 0
        if self.creditos < 0:
            raise ValidationError({"creditos": "Los créditos no pueden ser negativos."})
        if not self.seccion.strip():
            raise ValidationError({"seccion": "La sección no puede estar vacía."})
        if self.docente_id is not None and self.docente_id <= 0:
            raise ValidationError({"docente_id": "El identificador del docente debe ser mayor que cero."})
        if self.periodo_id <= 0:
            raise ValidationError({"periodo_id": "El identificador del periodo debe ser mayor que cero."})
        if not Periodo.objects.filter(id=self.periodo_id).exists():
            raise ValidationError({"periodo_id": "El periodo indicado no existe."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nrc} - {self.nombre}"
