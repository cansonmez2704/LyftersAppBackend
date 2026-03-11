from django.db.models import Q, F, Value, Prefetch
from django.db.models.functions import Greatest

from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework import permissions
from rest_framework.response import Response

from common.permissions import IsOwner
from common.reactions import toggle_reaction


from .serializers import (
    PostListSerializer, 
    PostDetailSerializer, 
    CommentSerializer,
    PostReactionSerializer,
    PostWriteSerializer 
)
from .models import Post, Comment, PostReaction, CommentReaction , ReactionType
from common.pagination import FeedCursorPagination, CommentLimitOffsetPagination

class PostViewSet(ModelViewSet):
   
    pagination_class = FeedCursorPagination

    def get_serializer_class(self):
      if self.action == 'retrieve':
        return PostDetailSerializer
     
      elif self.action in ["create","update","partial_update"]:
        return PostWriteSerializer
      
      return PostListSerializer

    def get_queryset(self):
     base_queryset = Post.objects.filter(is_deleted=False).select_related("author__profile")

     if not self.request.user.is_staff and self.request.user.is_authenticated:
        base_queryset = base_queryset.filter(
            Q(author=self.request.user) | Q(visibility=Post.Visibility.PUBLIC)
        )

     if self.action == 'retrieve':
        return base_queryset.prefetch_related(
        Prefetch(
            "comments",
            queryset=Comment.objects.filter(is_deleted=False)
                          .select_related("author__profile")
                          .prefetch_related("reactions__user__profile"),
        ),
        "media",
        "reactions__user__profile",
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
    
    @action(detail=True, methods=["POST"],url_path="react")
    def react_to_posts(self, request, pk=None):
     post = self.get_object()
     return toggle_reaction(
        reaction_model=PostReaction,
        parent_obj=post,
        parent_field_name="post",
        user=request.user,
        reaction_type=request.data.get("reaction_type"),
        valid_choices=[PostReaction.LIKE, PostReaction.DISLIKE],
     )
     
    
    @action(detail=True,methods=["GET"])
    def reactions(self,request,pk=None):
       post = self.get_object()
       reaction_qs = post.reactions.select_related("user__profile").all() 
       reaction_type = request.query_params.get('type')
       if reaction_type:
          reaction_qs = reaction_qs.filter(reaction_type=reaction_type)
       
       page = self.paginate_queryset(reaction_qs)
       if page is not None:
            serializer = PostReactionSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
       
       serializer = PostReactionSerializer(reaction_qs, many=True, context={'request': request})
       return Response(serializer.data)
  
 

class CommentViewSet(ModelViewSet):
    serializer_class = CommentSerializer
    pagination_class = CommentLimitOffsetPagination

    def get_permissions(self):
        if self.action in ['update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsOwner() | permissions.IsAdminUser()]
        return [permissions.IsAuthenticated()]  

    def get_queryset(self):
        queryset = Comment.objects.filter(is_deleted=False)

        if self.request.user.is_authenticated:
            queryset = queryset.filter(
                Q(post__visibility='public') | Q(post__author=self.request.user)
            )
        

        post_id = self.request.query_params.get('post')
        if post_id:
            queryset = queryset.filter(post_id=post_id)
        return queryset.select_related("post", "author__profile").prefetch_related("reactions__user__profile")

    def perform_create(self, serializer):
        post = serializer.validated_data.get('post')
        if post.visibility == 'private' and post.author != self.request.user:
            raise PermissionDenied("You cannot comment on this private post.")

        serializer.save(author=self.request.user)
        Post.objects.filter(id=post.id).update(comments_count=F("comments_count") + 1)
        
    def perform_destroy(self, instance):
     if instance.is_deleted:
        return

     instance.is_deleted = True
     instance.save(update_fields=['is_deleted'])

     Post.objects.filter(id=instance.post_id).update(
        comments_count=Greatest(F("comments_count") - 1, Value(0))
     )

    @action(detail=True, methods=["POST"],url_path="react")
    def react_to_comments(self, request, pk=None):
     comment = self.get_object()
     return toggle_reaction(
        reaction_model=CommentReaction,
        parent_obj=comment,
        parent_field_name="comment",
        user=request.user,
        reaction_type=request.data.get("reaction_type"),
        valid_choices=[ReactionType.LIKE, ReactionType.DISLIKE],
     )





