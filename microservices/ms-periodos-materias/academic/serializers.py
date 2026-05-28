from rest_framework import serializers
from django.core.files.uploadedfile import UploadedFile

from .models import Periodo, Materia


class PeriodoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Periodo
        fields = "__all__"
        read_only_fields = ("creado_en", "actualizado_en")

    def validate(self, attrs):
        fecha_inicio = attrs.get("fecha_inicio", getattr(self.instance, "fecha_inicio", None))
        fecha_fin = attrs.get("fecha_fin", getattr(self.instance, "fecha_fin", None))
        if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
            raise serializers.ValidationError(
                {"fecha_fin": "La fecha de fin debe ser mayor o igual a la fecha de inicio."}
            )
        return attrs


class MateriaSerializer(serializers.ModelSerializer):
    creditos = serializers.IntegerField(required=False, allow_null=True, min_value=0, default=0)

    class Meta:
        model = Materia
        fields = "__all__"
        read_only_fields = ("creado_en", "actualizado_en")

    def validate_creditos(self, value):
        if value in (None, ""):
            return 0
        return value

    def validate_docente_id(self, value):
        if value in (None, ""):
            return None
        if value <= 0:
            raise serializers.ValidationError("El identificador del docente debe ser mayor que cero.")
        return value

    def validate_periodo_id(self, value):
        if value <= 0:
            raise serializers.ValidationError("El identificador del periodo debe ser mayor que cero.")
        if not Periodo.objects.filter(id=value).exists():
            raise serializers.ValidationError("El periodo indicado no existe.")
        return value


class MateriaImportSerializer(serializers.Serializer):
    periodo_id = serializers.IntegerField(min_value=1)
    archivo = serializers.FileField(required=False, allow_null=True)
    texto = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        archivo = attrs.get("archivo")
        texto = attrs.get("texto", "").strip()
        if not archivo and not texto:
            raise serializers.ValidationError(
                {"archivo": "Debes enviar un archivo PDF o texto extraído para importar."}
            )
        if archivo is not None and not isinstance(archivo, UploadedFile):
            raise serializers.ValidationError({"archivo": "El archivo enviado no es válido."})
        return attrs
