from django.db.models import Q
from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework import permissions,status
from rest_framework.response import Response
from common.permissions import IsOwner
from .serializers import PostSerializer , CommentSerializer
from .models import Post , Comment

class PostViewSet(ModelViewSet):
    serializer_class = PostSerializer
    
    def get_queryset(self):
        queryset = Post.objects.filter(is_deleted=False).select_related("author__profile").prefetch_related("media","comments__author__profile","reactions__user__profile")
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(Q(author=self.request.user) | Q(visibility = Post.Visibility.PUBLIC))
    
    def get_permissions(self):
        if self.action in ['update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsOwner()]
        return [permissions.IsAuthenticated()]
        
    def perform_create(self, serializer):
        serializer.save(author=self.request.user)
        
    def perform_destroy(self, instance):
        instance.is_deleted = True
        instance.save(update_fields=['is_deleted'])
   
    
        

class CommentViewSet(ModelViewSet):
    serializer_class = CommentSerializer

    def get_queryset(self):
        return Comment.objects.filter(is_deleted=False).select_related("post","author__profile").prefetch_related("reactions__user__profile")
        
    def get_permissions(self):
        if self.action in ['update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsOwner()]
        return [permissions.IsAuthenticated()]
    
    def perform_create(self, serializer):
        serializer.save(author=self.request.user)
        
    def perform_destroy(self, instance):
        instance.is_deleted = True
        instance.save(update_fields=['is_deleted'])
    
   
