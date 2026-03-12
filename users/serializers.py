from rest_framework import serializers
from .models import UserProfile , User , UserFollower
from rest_framework.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, write_only=True)

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise ValidationError("Incorrect old password")
        return value
   
    def validate_new_password(self, value):
        try:
            validate_password(value, self.context['request'].user)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value 

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("uuid","username",)

class UserRegisterSerializer(serializers.ModelSerializer):
    confirm_password = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True)
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

class MiniUserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer()
    class Meta:
        model = UserProfile
        fields = ("user","avatar")  

class UserFollowerSerializer(serializers.ModelSerializer):
    to_user_profile = MiniUserProfileSerializer(source='to_user.profile', read_only=True)
    
    class Meta:
        model = UserFollower
        fields = ("from_user", "to_user", "to_user_profile", "status")

class FullUserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer()
    posts = serializers.SerializerMethodField()
    workouts = serializers.SerializerMethodField()
    follow = serializers.SerializerMethodField()
    

    class Meta:
        model = UserProfile
        fields = ("user","avatar","bio","follow","followers_count","following_count","height","weight","gender","birth_date","posts","workouts")
    
    def get_follow(self, obj):
        request = self.context.get('request')

        if not request or not request.user.is_authenticated:
            return None
            
        follower_record = UserFollower.objects.filter(
            from_user=request.user, 
            to_user=obj.user
        ).first()
        
        if follower_record:
            return follower_record.status
            
        return None
        
    def get_posts(self, obj):
        from community.serializers import PostListSerializer
        posts = (
            obj.user.posts                                  
            .filter(is_deleted=False)                       
            .select_related("author__profile")              
            .prefetch_related("media")                      
            .order_by("-created_at")[:10]                   
        )
        return PostListSerializer(posts, many=True).data        

    def get_workouts(self, obj):
        from workouts.serializers import WorkoutSerializer
        workouts = (
            obj.user.workouts                               
            .select_related("owner__profile")               
            .prefetch_related(                              
                "workout_exercises__exercise__muscles",      
                "workout_exercises__sets",                   
            )
            .order_by("-created_at")[:10]                   
        )
        return WorkoutSerializer(workouts, many=True).data  

