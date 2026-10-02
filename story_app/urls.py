from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='story_index'),
    path('create/', views.create_story, name='story_create'),
    path('story/<str:story_id>/', views.story_reader, name='story_reader'),
    path('story/<str:story_id>/progress/', views.story_progress, name='story_progress'),
    path('story/<str:story_id>/events/', views.story_events, name='story_events'),
    path('story/<str:story_id>/status/', views.story_status_api, name='story_status_api'),
    path('story/<str:story_id>/regenerate-page/', views.regenerate_page, name='regenerate_page'),
    path('story/<str:story_id>/resume/', views.resume_story, name='resume_story'),
    path('story/<str:story_id>/restart/', views.restart_story, name='restart_story'),
    path('story/<str:story_id>/delete/', views.delete_story, name='delete_story'),
    path('story/<str:story_id>/download-pdf/', views.download_pdf, name='download_pdf'),
    path('settings/', views.settings_view, name='settings'),
]
