from rest_framework.pagination import CursorPagination, LimitOffsetPagination

class FeedCursorPagination(CursorPagination):
    ordering = '-created_at' 
    page_size = 20

class CommentLimitOffsetPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 40