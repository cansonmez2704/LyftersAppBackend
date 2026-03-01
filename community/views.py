from django.db.models import Q , F
from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework import permissions,status
from rest_framework.response import Response
from common.permissions import IsOwner
from .serializers import PostSerializer , CommentSerializer
from .models import Post , Comment , PostReaction , CommentReaction

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
    
    @action(detail=True, methods=["POST"])
    def react_to_posts(self, request, pk=None):

        post = self.get_object()
        reaction_type = request.data.get("reaction_type")

     
        if reaction_type not in [PostReaction.ReactionType.LIKE, PostReaction.ReactionType.DISLIKE]:
            return Response(
                {"error": "Invalid reaction type. Must be 'like' or 'dislike'."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        existing_reaction = PostReaction.objects.filter(
            user=request.user,
            post=post,
        ).first()

        if not existing_reaction:
        
            PostReaction.objects.create(user=request.user, post=post, reaction_type=reaction_type)
            
            if reaction_type == PostReaction.ReactionType.LIKE:
                post.likes_count = F('likes_count') + 1
                post.save(update_fields=['likes_count'])
                return Response({"status": "Reaction added"}, status=status.HTTP_201_CREATED)
            else:
                post.dislikes_count = F('dislikes_count') + 1
                post.save(update_fields=['dislikes_count'])
                return Response({"status": "Reaction added"}, status=status.HTTP_201_CREATED)

        else:
            if existing_reaction.reaction_type == reaction_type:
           
                existing_reaction.delete()
                
                if reaction_type == PostReaction.ReactionType.LIKE:
                    post.likes_count = F('likes_count') - 1
                    post.save(update_fields=['likes_count'])
                    return Response({"status": "Reaction removed"}, status=status.HTTP_200_OK)
                else:
                    post.dislikes_count = F('dislikes_count') - 1
                    post.save(update_fields=['dislikes_count'])
                    return Response({"status": "Reaction removed"}, status=status.HTTP_200_OK)
               
                
            else:
               
                existing_reaction.reaction_type = reaction_type
                existing_reaction.save()
                
                if reaction_type == PostReaction.ReactionType.LIKE:
                    post.likes_count = F('likes_count') + 1
                    post.dislikes_count = F('dislikes_count') - 1
                    post.save(update_fields=['likes_count',"dislikes_count"])
                    return Response({"status": "Reaction changed"}, status=status.HTTP_200_OK)
                else:
                    post.dislikes_count = F('dislikes_count') + 1
                    post.likes_count = F('likes_count') - 1
                    post.save(update_fields=['dislikes_count',"likes_count"])
                    return Response({"status": "Reaction changed"}, status=status.HTTP_200_OK)
            



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
        
    
    @action(detail= True , methods=["POST"])
    def react_to_comment(self,request,pk=None):
        comment = self.get_object()
        reaction_type = request.data.get("reaction_type")

        if reaction_type not in [CommentReaction.ReactionType.LIKE , CommentReaction.ReactionType.DISLIKE]:
            return Response({"error": "Invalid reaction type. Must be 'like' or 'dislike'."},status=status.HTTP_400_BAD_REQUEST)
        
        existing_reaction = CommentReaction.objects.filter(
            comment = comment,
            user = request.user,
        ).first()

        if not existing_reaction:
            CommentReaction.objects.create(user=request.user,comment=comment,reaction_type=reaction_type)
            if reaction_type == CommentReaction.ReactionType.LIKE:
                comment.likes_count = F("likes_count") + 1
                comment.save(update_fields = ["likes_count"])
                return Response({"success":"Reaction recorded"},status=status.HTTP_200_OK)
            else:
                comment.dislikes_count = F("dislikes_count") + 1
                comment.save(update_fields = ["dislikes_count"])
                return Response({"success":"Reaction recorded"},status=status.HTTP_200_OK)
        else:
            if existing_reaction.reaction_type == reaction_type:
                existing_reaction.delete()
                if reaction_type == CommentReaction.ReactionType.LIKE:
                    comment.likes_count = F("likes_count") - 1
                    comment.save(update_fields = ["likes_count"])
                    return Response({"success":"Reaction removed"},status=status.HTTP_200_OK)
                else:
                    comment.dislikes_count = F("dislikes_count") - 1
                    comment.save(update_fields = ["dislikes_count"])
                    return Response({"success":"Reaction removed"},status=status.HTTP_200_OK)
            else:
                
                existing_reaction.reaction_type = reaction_type
                existing_reaction.save()
                if reaction_type == CommentReaction.ReactionType.LIKE:
                    comment.likes_count = F("likes_count") + 1
                    comment.dislikes_count = F("dislikes_count") - 1
                    comment.save(update_fields = ["likes_count","dislikes_count"])
                    return Response({"success":"Reaction changed"},status=status.HTTP_200_OK)
                else:
                    comment.dislikes_count = F("dislikes_count") + 1
                    comment.likes_count = F("likes_count") - 1
                    comment.save(update_fields = ["dislikes_count","likes_count"])
                    return Response({"success":"Reaction changed"},status=status.HTTP_200_OK)

                  
