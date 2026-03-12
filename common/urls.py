from django.urls import path
from .search import GlobalSearchView

urlpatterns = [
    path("search/", GlobalSearchView.as_view(), name="global-search"),
]
