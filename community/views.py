from django.db.models import Q , F
from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework import permissions,status
from rest_framework.response import Response
from common.permissions import IsOwner
from .serializers import PostListSerializer , PostDetailSerializer , CommentSerializer
from .models import Post , Comment , PostReaction , CommentReaction
from common.reactions import toggle_reaction


class PostViewSet(ModelViewSet):
   

    def get_serializer_class(self):
        if self.action == 'list':
            return PostListSerializer
        return PostDetailSerializer

    def get_queryset(self):
     base_queryset = Post.objects.filter(is_deleted=False).select_related("author__profile")

     if not self.request.user.is_staff:
        base_queryset = base_queryset.filter(
            Q(author=self.request.user) | Q(visibility=Post.Visibility.PUBLIC)
        )

     if self.action in ['retrieve', 'react_to_posts']:
        return base_queryset.prefetch_related(
            "media", "comments__author__profile", "reactions__user__profile"
        )

     return base_queryset.prefetch_related("media")
    
    def get_permissions(self):
        if self.action in ['update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsOwner()]
        return [permissions.IsAuthenticated()]
        
    def perform_create(self, serializer):
        serializer.save(author=self.request.user)
        
    def perform_destroy(self, instance):
        instance.is_deleted = True
        instance.save(update_fields=['is_deleted'])
    
    @action(detail=True, methods=["POST"])
    def react_to_posts(self, request, pk=None):
     post = self.get_object()
     msg, code = toggle_reaction(
        reaction_model=PostReaction,
        parent_obj=post,
        parent_field_name="post",
        user=request.user,
        reaction_type=request.data.get("reaction_type"),
        valid_choices=[PostReaction.ReactionType.LIKE, PostReaction.ReactionType.DISLIKE],
     )
     return Response({"status": msg}, status=code)
  


class CommentViewSet(ModelViewSet):
    serializer_class = CommentSerializer

    def get_queryset(self):
        return Comment.objects.filter(is_deleted=False).select_related("post","author__profile").prefetch_related("reactions__user__profile")
        
    def get_permissions(self):
        if self.action in ['update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsOwner()]
        return [permissions.IsAuthenticated()]
    
    def perform_create(self,serializer):
       comment = serializer.save(author=self.request.user)
       post_id = comment.post.id
       Post.objects.filter(id=post_id).update(comments_count = F("comments_count")+1)
        
    def perform_destroy(self, instance):
        instance.is_deleted = True
        instance.save(update_fields=['is_deleted'])
        post_id = instance.post.id
        Post.objects.filter(id=post_id).update(comments_count = F("comments_count")-1)
    
    @action(detail=True, methods=["POST"])
    def react_to_comments(self, request, pk=None):
        comment = self.get_object()
        msg, code = toggle_reaction(
            reaction_model=CommentReaction,
            parent_obj=comment,
            parent_field_name="comment",
            user=request.user,
            reaction_type=request.data.get("reaction_type"),
            valid_choices=[CommentReaction.ReactionType.LIKE, CommentReaction.ReactionType.DISLIKE],
        )
        return Response({"status": msg}, status=code)
    
    