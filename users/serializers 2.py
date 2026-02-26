from rest_framework import serializers
from .models import UserProfile , User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id","uuid","username",)

class UserRegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("username","password","email","confirm_password")    

class UserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer()
    class Meta:
        model = UserProfile
        fields = ("user","avatar","bio","height","weight","gender","birth_date")

class MiniUserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer()
    class Meta:
        model = UserProfile
        fields = ("user","avatar","bio")    