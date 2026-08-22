from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="get_full_name", read_only=True)
    is_locked = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "role",
            "is_active",
            "is_locked",
            "locked_until",
            "last_login",
            "date_joined",
        ]
        read_only_fields = ["id", "date_joined", "locked_until", "last_login"]

    def validate(self, attrs):
        _guard_role_assignment(self.context, attrs, instance=self.instance)
        return attrs


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "password",
            "role",
            "is_active",
        ]

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate(self, attrs):
        _guard_role_assignment(self.context, attrs, instance=self.instance)
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


def _guard_role_assignment(context, attrs, instance=None):
    """Only admins may assign the ADMIN role or modify admin accounts."""
    request = context.get("request") if context else None
    user = getattr(request, "user", None) if request else None
    if user is None or not getattr(user, "is_authenticated", False):
        return
    if user.is_admin:
        return
    if attrs.get("role") == User.Role.ADMIN:
        raise serializers.ValidationError(
            {"role": "Only admins can assign the ADMIN role."}
        )
    if instance is not None and instance.is_admin:
        raise serializers.ValidationError(
            {"role": "Only admins can modify admin accounts."}
        )


class AdminSetPasswordSerializer(serializers.Serializer):
    """Admin-initiated password reset (distinct from a self-service change:
    no old-password confirmation, since the acting admin isn't the account
    owner)."""

    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_password(self, value):
        validate_password(value, user=self.context.get("target_user"))
        return value


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class LoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    user = UserSerializer()
