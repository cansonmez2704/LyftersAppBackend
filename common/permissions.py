from rest_framework import permissions

class IsOwnerOrReadOnly(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        elif hasattr(obj,"owner"):
            return obj.owner == request.user or request.user.is_staff
        elif hasattr(obj,"author"):
            return obj.author == request.user or request.user.is_staff
        elif hasattr(obj,"user"):
            return obj.user == request.user or request.user.is_staff
        else:
            return False
        
         
        