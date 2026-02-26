from rest_framework import serializers
from users.serializers import MiniUserProfileSerializer
from .models import Post , PostMedia , PostReaction , Comment , CommentReaction

class PostMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostMedia
        fields = ("id","media_type","file","order","alt_text")

class PostReactionSerializer(serializers.ModelSerializer):
    user = MiniUserProfileSerializer(read_only=True)
    class Meta:
        model = PostReaction
        fields = ("user","reaction_type","created_at",)

class CommentReactionSerializer(serializers.ModelSerializer):
    user = MiniUserProfileSerializer(read_only=True)
    class Meta:
        model = CommentReaction
        fields = ("user","reaction_type","created_at",)

class CommentSerializer(serializers.ModelSerializer):
    reactions = CommentReactionSerializer(read_only=True)
    author = MiniUserProfileSerializer(read_only=True)
    class Meta:
        model = Comment
        fields = ("id","author","parent","body","likes_count","dislikes_count","reactions","is_deleted","created_at","updated_at",)

class PostSerializer(serializers.ModelSerializer):
    author = MiniUserProfileSerializer(read_only=True)
    comment = CommentSerializer()
    post_media = PostMediaSerializer()
    class Meta:
        model = Post
        fields = ("author","title","description","cover_image","post_type","visibility","linked_workouts")


