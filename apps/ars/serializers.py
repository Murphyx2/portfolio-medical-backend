from rest_framework import serializers

from apps.ars.models import ARS, ARSProgram


class ARSProgramSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = ARSProgram
        fields = ["id", "name"]


class ARSSerializer(serializers.ModelSerializer):
    programs = ARSProgramSerializer(many=True, required=False)

    class Meta:
        model = ARS
        fields = ["id", "ars_id", "name", "programs"]

    def create(self, validated_data):
        programs = validated_data.pop("programs", [])
        ars = ARS.objects.create(**validated_data)
        self._set_programs(ars, programs)
        return ars

    def update(self, instance, validated_data):
        programs = validated_data.pop("programs", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if programs is not None:
            self._set_programs(instance, programs)
        return instance

    @staticmethod
    def _set_programs(ars, programs):
        keep_ids = []
        for item in programs:
            name = (item.get("name") or "").strip()
            if not name:
                continue
            program_id = item.get("id")
            if program_id:
                program = ARSProgram.objects.filter(pk=program_id, ars=ars).first()
                if program is not None:
                    if program.name != name:
                        program.name = name
                        program.save()
                    keep_ids.append(program.pk)
                    continue
            keep_ids.append(ARSProgram.objects.create(ars=ars, name=name).pk)
        ars.programs.exclude(pk__in=keep_ids).delete()
