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
    author = MiniUserProfileSerializer(source="author.profile", read_only=True)

    class Meta:
        model = Comment
        fields = (
            "id", "author", "parent", "post", "body",
            "likes_count", "dislikes_count","is_deleted", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "author", "likes_count", "dislikes_count",
            "is_deleted", "created_at", "updated_at",
        )
    def to_representation(self, instance): 
        data = super().to_representation(instance)
        
        if instance.is_deleted:
            data['body'] = "[deleted]"
            data['author'] = None
            data['likes_count'] = 0
            data['dislikes_count'] = 0
            
        return data

    def validate(self, attrs):
        parent = attrs.get('parent')
        post = attrs.get('post')
        if parent:
            if parent.post != post:
                raise serializers.ValidationError("Replies must belong to the same post.")
            if parent.is_deleted:
                raise serializers.ValidationError("Cannot reply to a deleted comment.")
            if parent.depth >= 3:
                raise serializers.ValidationError("Maximum nesting depth reached.")
        return attrs




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
    user_reaction = serializers.SerializerMethodField() 
    
    class Meta(PostListSerializer.Meta):
        fields = PostListSerializer.Meta.fields + (
            "comments", "user_reaction",
        )
        read_only_fields = PostListSerializer.Meta.read_only_fields + (
            "comments", "user_reaction",
        )

    def get_user_reaction(self, obj): 
        request = self.context.get("request")
        if not request or request.user.is_anonymous:
            return None
        
        user = request.user
        reaction = next((r for r in obj.reactions.all() if r.user_id == user.id), None)
        return reaction.reaction_type if reaction else None
    
    def get_comments(self, obj):
        return CommentSerializer(obj.comments.all(), many=True, context=self.context).data


class PostMediaWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostMedia
        fields = ("media_type", "file", "order", "alt_text")


class PostWriteSerializer(serializers.ModelSerializer):
    media = PostMediaWriteSerializer(many=True, required=False)
    class Meta:
        model = Post
        fields = ("title", "description", "cover_image", "post_type", "visibility", "linked_workout", "media")
    def create(self, validated_data):
        media_data = validated_data.pop("media", [])
        post = Post.objects.create(**validated_data)
        PostMedia.objects.bulk_create([
            PostMedia(post=post, **item) for item in media_data
        ])
        return post

    def update(self, instance, validated_data):
        media_data = validated_data.pop("media", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if media_data is not None:
            instance.media.all().delete()
            PostMedia.objects.bulk_create([
                PostMedia(post=instance, **item) for item in media_data
            ])
        return instance

    