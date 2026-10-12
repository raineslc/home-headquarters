from django.urls import path
from django.contrib.auth.views import LogoutView
from organizer import views

urlpatterns = [
    path('health/', views.health),
    path('sign-in/', views.SignIn.as_view(), name='login'),
    path('sign-out/', LogoutView.as_view(), name='logout'),
    path('setup/', views.setup, name='setup'),
    path('', views.home, name='home'),
    path('foundation/records/', views.records, name='records'),
    path('foundation/export/', views.export, name='export'),
    path('foundation/restore/', views.restore, name='restore'),
    path('foundation/recovery/', views.recovery_points, name='recovery'),
    path('foundation/recovery/<uuid:point_id>/', views.recovery_download, name='recovery_download'),
]
