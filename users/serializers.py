from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from .models import UserFollower, User, UserProfile


# ------------------------------------------
# Avatar processing
# Server-side normalisation runs on every upload regardless of what the client
# claims it sent. It:
#   1. Applies EXIF orientation then discards all metadata (GPS leak defense).
#   2. Resizes the image so the longest edge is at most AVATAR_MAX_DIMENSION.
#   3. Re-encodes as WebP for bandwidth/storage savings on S3.
# ------------------------------------------

AVATAR_MAX_DIMENSION = 500
AVATAR_WEBP_QUALITY = 85


def process_avatar_upload(uploaded_file):
    """Normalise an uploaded avatar into a stripped, resized WebP file.

    The returned object is an InMemoryUploadedFile that Django's ImageField
    accepts transparently, so `upload_to` + the storage backend handle the
    rest of the pipeline (path generation, S3 streaming).
    """
    try:
        uploaded_file.seek(0)
        img = Image.open(uploaded_file)
        img.load()
    except (UnidentifiedImageError, OSError):
        raise serializers.ValidationError(
            "Avatar could not be read. Please upload a valid JPG, PNG, or WebP image."
        )

    img = ImageOps.exif_transpose(img) or img

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")

    img.thumbnail(
        (AVATAR_MAX_DIMENSION, AVATAR_MAX_DIMENSION),
        Image.LANCZOS,
    )

    buffer = BytesIO()
    img.save(
        buffer,
        format="WEBP",
        quality=AVATAR_WEBP_QUALITY,
        method=6,
    )
    buffer.seek(0)

    base_name = (getattr(uploaded_file, "name", "avatar") or "avatar").rsplit(".", 1)[0]
    return InMemoryUploadedFile(
        file=buffer,
        field_name="avatar",
        name=f"{base_name}.webp",
        content_type="image/webp",
        size=buffer.getbuffer().nbytes,
        charset=None,
    )


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
        fields = ("uuid", "username", "password", "email", "confirm_password")
        read_only_fields = ("uuid",)

    def validate_username(self, value):
        # Strip incidental whitespace so "  alice" and "alice" cannot coexist
        # as distinct accounts.
        normalized = (value or "").strip()
        if not normalized:
            raise serializers.ValidationError("Username is required.")
        return normalized

    def validate_email(self, value):
        # Normalize case and whitespace to prevent duplicate-account squatting
        # via case variants (e.g. "Foo@Example.com" vs "foo@example.com").
        # Django's normalize_email only lower-cases the domain, so we force the
        # local part to lowercase too — mail providers in practice treat the
        # local part as case-insensitive.
        normalized = User.objects.normalize_email((value or "").strip()).lower()
        if not normalized:
            raise serializers.ValidationError("Email is required.")
        return normalized

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
        fields = ("user","avatar","bio","is_public","follow","followers_count","following_count","height","weight","gender","birth_date","onboarding_completed","posts","workouts")

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
        if not value:
            return value

        max_size = settings.MAX_AVATAR_UPLOAD_SIZE
        if value.size > max_size:
            actual_size_mb = value.size / (1024 * 1024)
            limit_mb = max_size / (1024 * 1024)
            raise serializers.ValidationError(
                f"Avatar file size must be under {limit_mb:.0f} MB. Your file is {actual_size_mb:.2f} MB."
            )

        return process_avatar_upload(value)

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
        if not value:
            return value

        max_size = settings.MAX_AVATAR_UPLOAD_SIZE
        if value.size > max_size:
            actual_size_mb = value.size / (1024 * 1024)
            limit_mb = max_size / (1024 * 1024)
            raise serializers.ValidationError(
                f"Avatar file size must be under {limit_mb:.0f} MB. Your file is {actual_size_mb:.2f} MB."
            )

        return process_avatar_upload(value)


class FollowerEdgeSerializer(serializers.Serializer):
    """Thin adapter so follower/following list endpoints can paginate the
    `UserFollower` queryset (ordered by follow recency) while still returning
    the same flat `MiniUserProfileSerializer` shape the client already knows.
    """

    side = "from_user"  # overridden by subclasses

    def to_representation(self, instance):
        profile = getattr(instance, self.side).profile
        return MiniUserProfileSerializer(profile, context=self.context).data


class FollowerListEntrySerializer(FollowerEdgeSerializer):
    side = "from_user"


class FollowingListEntrySerializer(FollowerEdgeSerializer):
    side = "to_user"


class IncomingFollowRequestSerializer(serializers.ModelSerializer):
    from_user_profile = MiniUserProfileSerializer(source="from_user.profile", read_only=True)
    from_user_uuid = serializers.UUIDField(source="from_user.uuid", read_only=True)

    class Meta:
        model = UserFollower
        fields = ("from_user_uuid", "from_user_profile", "status", "created_at")

