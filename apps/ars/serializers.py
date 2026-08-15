from rest_framework import serializers

from apps.ars.models import ARS, ARSProgram
from apps.core.serializers import CoreModelSerializer


class ARSProgramSerializer(CoreModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = ARSProgram
        fields = ["id", "name", "active"]


class ARSSerializer(CoreModelSerializer):
    programs = ARSProgramSerializer(many=True, required=False)

    class Meta:
        model = ARS
        fields = ["id", "ars_id", "name", "programs", "active"]

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
                # all_objects: a previously-deactivated program is still
                # findable by id here, so re-adding it revives it instead of
                # creating a duplicate.
                program = ARSProgram.all_objects.filter(pk=program_id, ars=ars).first()
                if program is not None:
                    changed = False
                    if program.name != name:
                        program.name = name
                        changed = True
                    if not program.active:
                        program.active = True
                        changed = True
                    if changed:
                        program.save()
                    keep_ids.append(program.pk)
                    continue
            keep_ids.append(ARSProgram.objects.create(ars=ars, name=name).pk)
        # ars.programs is already active-only (SoftDeleteManager as the
        # default manager), so this only ever touches currently-active
        # programs omitted from the payload -- deactivate instead of delete.
        ars.programs.exclude(pk__in=keep_ids).update(active=False)
