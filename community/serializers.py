from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from users.serializers import MiniUserProfileSerializer
from .models import Post, PostMedia, PostReaction, Comment, CommentReaction, POST_DESCRIPTION_MAX_LENGTH
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.urls import reverse


class PostMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostMedia
        fields = ("id", "media_type", "file", "order", "alt_text")


class PostReactionSerializer(serializers.ModelSerializer):
    user = MiniUserProfileSerializer(source="user.profile", read_only=True)

    class Meta:
        model = PostReaction
        fields = ("user", "reaction_type", "created_at",)


class CommentReactionSerializer(serializers.ModelSerializer):
    user = MiniUserProfileSerializer(source="user.profile", read_only=True)

    class Meta:
        model = CommentReaction
        fields = ("user", "reaction_type", "created_at",)


class CommentSerializer(serializers.ModelSerializer):
    author = MiniUserProfileSerializer(source="author.profile", read_only=True)

    class Meta:
        model = Comment
        fields = (
            "uuid",
            "author",
            "parent",
            "post",
            "body",
            "likes_count",
            "dislikes_count",
            "is_deleted",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "uuid",
            "author",
            "post",
            "likes_count",
            "dislikes_count",
            "is_deleted",
            "created_at",
            "updated_at",
        )

    def to_representation(self, instance):
        data = super().to_representation(instance)

        if instance.is_deleted:
            data['body'] = "[deleted]"
            data['author'] = None
            data['likes_count'] = 0
            data['dislikes_count'] = 0
        return data

    def validate(self, data):
        view = self.context.get("view")
        post = None
        if view is not None:
            post_uuid = view.kwargs.get("post_uuid")
            if post_uuid:
                post = Post.objects.filter(
                    uuid=post_uuid, is_deleted=False
                ).first()

        instance = Comment(**{**data, "post": post} if post else data)
        try:
            instance.clean()
        except DjangoValidationError as e:
            raise serializers.ValidationError(
                e.message_dict if hasattr(e, 'message_dict') else str(e)
            )

        data['depth'] = instance.depth
        return data


class PostListSerializer(serializers.ModelSerializer):
    author = MiniUserProfileSerializer(source="author.profile", read_only=True)
    media = PostMediaSerializer(read_only=True, many=True)

    class Meta:
        model = Post
        fields = (
            "id", "uuid", "author", "title", "description",
            "cover_image", "post_type", "visibility", "media", "likes_count",
            "dislikes_count", "comments_count", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "uuid", "author", "likes_count",
            "dislikes_count", "comments_count",
            "created_at", "updated_at",
        )


class PostDetailSerializer(PostListSerializer):
    user_reaction = serializers.SerializerMethodField()
    comments_url = serializers.SerializerMethodField()

    class Meta(PostListSerializer.Meta):
        fields = PostListSerializer.Meta.fields + (
            "user_reaction", "comments_url",
        )
        read_only_fields = PostListSerializer.Meta.read_only_fields + (
            "user_reaction", "comments_url",
        )

    def get_user_reaction(self, obj):
        request = self.context.get("request")
        if not request or request.user.is_anonymous:
            return None

        # `reactions` is no longer prefetched on retrieve — hit the index directly.
        reaction = (
            obj.reactions
            .filter(user_id=request.user.id)
            .values_list("reaction_type", flat=True)
            .first()
        )
        return reaction

    def get_comments_url(self, obj):
        """Paginated comment list lives at /posts/<uuid>/comments/."""
        request = self.context.get("request")
        path = reverse("post-comments", kwargs={"post_uuid": obj.uuid})
        return request.build_absolute_uri(path) if request else path


class PostMediaWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostMedia
        fields = ("media_type", "file", "order", "alt_text")

    def validate(self, data):
        instance = PostMedia(**data)
        try:
            instance.clean()
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message_dict if hasattr(e, 'message_dict') else str(e))
        return data


class PostWriteSerializer(serializers.ModelSerializer):
    media = PostMediaWriteSerializer(many=True, required=False)
    description = serializers.CharField(max_length=POST_DESCRIPTION_MAX_LENGTH)

    class Meta:
        model = Post
        fields = ("title", "description", "cover_image", "post_type", "visibility", "linked_workout", "media")

    def create(self, validated_data):
        with transaction.atomic():
            media_data = validated_data.pop("media", [])
            post = Post.objects.create(**validated_data)

            # PostMediaWriteSerializer.validate already ran clean() on each
            # item during is_valid(), so we skip full_clean() here — that call
            # would issue one S3 HEAD per file to read `size`.
            media_objs = [PostMedia(post=post, **item) for item in media_data]
            created = PostMedia.objects.bulk_create(media_objs)

            from .tasks import process_post_media
            for media in created:
                if media.pk and media.media_type == PostMedia.MediaType.IMAGE:
                    transaction.on_commit(
                        lambda mid=media.pk: process_post_media.delay(mid)
                    )

            return post

    def update(self, instance, validated_data):
        with transaction.atomic():
            media_data = validated_data.pop("media", None)
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()
            if media_data is not None:
                instance.media.all().delete()
                created = PostMedia.objects.bulk_create([
                    PostMedia(post=instance, **item) for item in media_data
                ])

                from .tasks import process_post_media
                for media in created:
                    if media.pk and media.media_type == PostMedia.MediaType.IMAGE:
                        transaction.on_commit(
                            lambda mid=media.pk: process_post_media.delay(mid)
                        )
            return instance
