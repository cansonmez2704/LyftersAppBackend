from rest_framework import serializers
from .models import UserProfile , User
from django.core.exceptions import ValidationError


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id","uuid","username",)

class UserRegisterSerializer(serializers.ModelSerializer):
    confirm_password = serializers.CharField(write_only=True)
    class Meta:
        model = User
        fields = ("username","password","email","confirm_password")    
    
    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise ValidationError("Passwords do not match")
        return attrs
    
    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"]
        )
        return user

class UserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer()
    class Meta:
        model = UserProfile
        fields = ("user","avatar","bio","height","weight","gender","birth_date")

class MiniUserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer()
    class Meta:
        model = UserProfile
        fields = ("user","avatar")    