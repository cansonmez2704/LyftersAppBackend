from rest_framework import serializers
from users.serializers import MiniUserProfileSerializer
from .models import Post , PostMedia , PostReaction , Comment , CommentReaction

class PostMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostMedia
        fields = ("id","media_type","file","order","alt_text")

class PostReactionSerializer(serializers.ModelSerializer):
    user = MiniUserProfileSerializer(source="user.profile",read_only=True)
    class Meta:
        model = PostReaction
        fields = ("user","reaction_type","created_at",)

class CommentReactionSerializer(serializers.ModelSerializer):
    user = MiniUserProfileSerializer(source="user.profile",read_only=True)
    class Meta:
        model = CommentReaction
        fields = ("user","reaction_type","created_at",)

class CommentSerializer(serializers.ModelSerializer):
    reactions = CommentReactionSerializer(many=True, read_only=True)
    author = MiniUserProfileSerializer(source="author.profile", read_only=True)

    class Meta:
        model = Comment
        fields = (
            "id", "author", "parent", "post", "body",
            "likes_count", "dislikes_count", "reactions",
            "is_deleted", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "author", "likes_count", "dislikes_count",
            "is_deleted", "created_at", "updated_at",
        )



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
    comments = serializers.SerializerMethodField()
    reactions = PostReactionSerializer(read_only=True, many=True)
    class Meta(PostListSerializer.Meta):
        fields = PostListSerializer.Meta.fields + (
            "comments", "reactions",
        )
        read_only_fields = PostListSerializer.Meta.read_only_fields + (
            "comments", "reactions",
        )
    
    def get_comments(self,obj):
        return CommentSerializer(obj.comments.all(), many=True).data

