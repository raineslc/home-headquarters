from django.urls import path
from django.contrib.auth.views import LogoutView
from organizer import views
from organizer import planner
from organizer import connections, invitations
from organizer import assistant

urlpatterns = [
    path('assistant/', assistant.index, name='assistant'),
    path('assistant/<uuid:pk>/', assistant.detail, name='assistant_plan'),
    path('assistant/<uuid:pk>/revise/', assistant.revise, name='assistant_revise'),
    path('tasks/<uuid:pk>/search/', assistant.task_search, name='task_search'),
    path('connections/google/', connections.index, name='google_connections'),
    path('connections/google/connect/', connections.begin, name='google_begin'),
    path('connections/google/callback/', connections.callback, name='google_callback'),
    path('connections/google/<uuid:pk>/choices/', connections.choices, name='google_choices'),
    path('connections/google/<uuid:pk>/sync/', connections.sync, name='google_sync'),
    path('connections/google/<uuid:pk>/disconnect/', connections.disconnect, name='google_disconnect'),
    path('connections/google/event/<uuid:pk>/', connections.event_detail, name='google_event'),
    path('settings/parents/', invitations.index, name='parents'),
    path('settings/parents/<uuid:pk>/cancel/', invitations.cancel, name='cancel_invite'),
    path('join/', invitations.join, name='parent_join'),
    path('health/', views.health),
    path('sign-in/', views.SignIn.as_view(), name='login'),
    path('sign-out/', LogoutView.as_view(), name='logout'),
    path('setup/', views.setup, name='setup'),
    path('', planner.dashboard, name='home'),
    path('family/', planner.family, name='family'),
    path('tasks/', planner.tasks, name='tasks'),
    path('lunches/', planner.lunches, name='lunches'),
    path('lunches/undo/', planner.undo_lunch, name='undo_lunch'),
    path('settings/', planner.settings, name='settings'),
    path('activity/<uuid:pk>/', planner.activity_detail, name='activity_detail'),
    path('plan/activity/bulk/', planner.bulk_activity, name='bulk_activity'),
    path('plan/<str:kind>/new/', planner.edit, name='plan_new'),
    path('plan/<str:kind>/<uuid:pk>/edit/', planner.edit, name='plan_edit'),
    path('plan/<str:kind>/<uuid:pk>/remove/', planner.remove, name='plan_remove'),
    path('tasks/<uuid:pk>/complete/', planner.complete, name='complete'),
    path('foundation/', views.home, name='foundation'),
    path('foundation/records/', views.records, name='records'),
    path('foundation/export/', views.export, name='export'),
    path('foundation/restore/', views.restore, name='restore'),
    path('foundation/recovery/', views.recovery_points, name='recovery'),
    path('foundation/recovery/<uuid:point_id>/', views.recovery_download, name='recovery_download'),
]
