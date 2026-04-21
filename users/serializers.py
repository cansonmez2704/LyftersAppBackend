from rest_framework import serializers
from .models import UserProfile , User , UserFollower
from rest_framework.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from core.settings import MAX_AVATAR_UPLOAD_SIZE , MAX_IMAGE_UPLOAD_SIZE , MAX_VIDEO_UPLOAD_SIZE


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
        
    

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

    def validate(self, attrs):
        if attrs.get("password") != attrs.get("confirm_password"):
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )
        return attrs

    def create(self, validated_data):
        validated_data.pop("confirm_password", None)
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
        # Mini profile is used in public-ish contexts (suggestions, followers lists,
        # reactions, etc.). Keep it intentionally small to avoid leaking sensitive
        # personal data.
        fields = ("user", "avatar", "bio", "is_public", "followers_count", "following_count")

class OwnProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer()
    posts = serializers.SerializerMethodField()
    workouts = serializers.SerializerMethodField()
    follow = serializers.SerializerMethodField()
    

    class Meta:
        model = UserProfile
        fields = ("user","avatar","bio","is_public","follow","followers_count","following_count","height","weight","gender","birth_date","posts","workouts")

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


    def validate_avatar(self, value):
        if value:

            if value.size > MAX_AVATAR_UPLOAD_SIZE:

                actual_size_mb = value.size / (1024 * 1024)
                limit_mb = MAX_AVATAR_UPLOAD_SIZE / (1024 * 1024)

                raise serializers.ValidationError(
                    f"Avatar file size must be under {limit_mb:.0f} MB. Your file is {actual_size_mb:.2f} MB."
                )

        return value

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
        fields = (
            "user",
            "avatar",
            "bio",
            "is_public",
            "follow",
            "followers_count",
            "following_count",
            "height",
            "weight",
            "gender",
            "birth_date",
            "posts",
            "workouts",
        )
    
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
    
    
    def validate_avatar(self, value):
        if value:
            
            if value.size > MAX_AVATAR_UPLOAD_SIZE:
           
                actual_size_mb = value.size / (1024 * 1024)
                limit_mb = MAX_AVATAR_UPLOAD_SIZE / (1024 * 1024)
                
                raise serializers.ValidationError(
                    f"Avatar file size must be under {limit_mb:.0f} MB. Your file is {actual_size_mb:.2f} MB."
                )
                
        return value


class IncomingFollowRequestSerializer(serializers.ModelSerializer):
    from_user_profile = MiniUserProfileSerializer(source="from_user.profile", read_only=True)
    from_user_uuid = serializers.UUIDField(source="from_user.uuid", read_only=True)

    class Meta:
        model = UserFollower
        fields = ("from_user_uuid", "from_user_profile", "status", "created_at")

