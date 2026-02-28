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
    reactions = CommentReactionSerializer(many=True,read_only=True)
    author = MiniUserProfileSerializer(source="author.profile",read_only=True)
    class Meta:
        model = Comment
        fields = ("id","author","parent","post","body","likes_count","dislikes_count","reactions","is_deleted","created_at","updated_at",)

class PostSerializer(serializers.ModelSerializer):
    author = MiniUserProfileSerializer(source="author.profile",read_only=True)
    comments = CommentSerializer(read_only=True,many=True)
    media = PostMediaSerializer(read_only=True,many=True)
    class Meta:
        model = Post
        fields = ("id","uuid","author","title","description","cover_image","post_type","visibility","comments","media","likes_count","dislikes_count","comments_count","linked_workout")


