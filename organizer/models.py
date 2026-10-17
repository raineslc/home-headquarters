import uuid
from django.conf import settings
from django.db import models

class Household(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    timezone = models.CharField(max_length=64, default='America/New_York')
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

class Membership(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=[('parent', 'Parent')], default='parent')
    active = models.BooleanField(default=True)

class SetupRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

class RecoveryPoint(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

class PendingRestore(models.Model):
    """A validated export awaiting confirmation; kept out of the session because exports can be large."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    household_version = models.PositiveIntegerField()
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

class BootstrapState(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    used_at = models.DateTimeField(null=True)

class RateLimit(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    attempts = models.PositiveIntegerField(default=0)
    window_start = models.DateTimeField()

class JobRun(models.Model):
    key = models.CharField(max_length=80, unique=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=20, default='running')

class FamilyMember(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    role = models.CharField(max_length=10, choices=[('parent', 'Parent'), ('child', 'Child')])
    color = models.CharField(max_length=12, choices=[('green', 'Green'), ('blue', 'Blue'), ('purple', 'Purple'), ('orange', 'Orange')], default='green')
    archived = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)

    def __str__(self):
        return self.name

    @property
    def initials(self):
        return ''.join(part[0] for part in self.name.split()[:2]).upper()

class Activity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    all_day = models.BooleanField(default=False)
    timezone = models.CharField(max_length=64, default='America/New_York')
    location = models.CharField(max_length=300, blank=True)
    notes = models.TextField(max_length=5000, blank=True)
    participants = models.ManyToManyField(FamilyMember, blank=True)
    version = models.PositiveIntegerField(default=1)
    reminder_minutes = models.PositiveIntegerField(null=True, blank=True)
    # A series stores an RFC 5545 RRULE anchored on start_date; skipped or changed dates are
    # listed in recurrence_exdates. A changed occurrence is its own Activity with series set.
    recurrence = models.CharField(max_length=300, blank=True)
    recurrence_exdates = models.JSONField(default=list, blank=True)
    series = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='overrides')
    occurrence_date = models.DateField(null=True, blank=True)
    # Activities added together on several dates share a batch ID; it makes the bulk create idempotent.
    batch = models.UUIDField(null=True, blank=True, db_index=True)
    # Optional copy in the household's family Google calendar (GGL-02). The app is the source of truth.
    google_sync = models.BooleanField(default=False)
    google_calendar = models.ForeignKey('GoogleCalendar', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    google_event_id = models.CharField(max_length=1024, blank=True)
    google_etag = models.CharField(max_length=255, blank=True)
    google_state = models.CharField(max_length=12, blank=True, choices=[
        ('synced', 'In Google Calendar'), ('pending', 'Waiting for Google'), ('failed', 'Google update failed'),
        ('conflict', 'Changed in Google'), ('removed', 'Deleted in Google')])
    google_error = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['start_date', 'start_time', 'title']
        constraints = [models.UniqueConstraint(fields=['series', 'occurrence_date'], name='one_override_per_occurrence')]

    def __str__(self):
        return self.title

class Task(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    high_priority = models.BooleanField(default=False)
    assignee = models.ForeignKey(FamilyMember, null=True, blank=True, on_delete=models.SET_NULL)
    activity = models.ForeignKey(Activity, null=True, blank=True, on_delete=models.SET_NULL, related_name='tasks')
    due_date = models.DateField(null=True, blank=True)
    due_time = models.TimeField(null=True, blank=True)
    notes = models.TextField(max_length=5000, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    reminder_minutes = models.PositiveIntegerField(null=True, blank=True)
    search_prompt = models.CharField(max_length=500, blank=True)
    search_questions = models.CharField(max_length=500, blank=True)
    # Repeating tasks: completing one creates the next due date once; series_key + due_date is unique.
    recurrence = models.CharField(max_length=300, blank=True)
    recurrence_start = models.DateField(null=True, blank=True)
    series_key = models.UUIDField(null=True, blank=True)
    # When set, the next task is due the rule's interval after the day it was completed (TSK-03).
    repeat_after_done = models.BooleanField(default=False)

    class Meta:
        ordering = ['-high_priority', 'due_date', 'title']
        constraints = [models.UniqueConstraint(fields=['series_key', 'due_date'], name='one_task_per_series_date')]

    @property
    def checklist_progress(self):
        items = list(self.checklist_items.values_list('done_at', flat=True))
        return (sum(1 for done in items if done), len(items))

class LunchPlan(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    child = models.ForeignKey(FamilyMember, on_delete=models.CASCADE)
    date = models.DateField()
    choice = models.CharField(max_length=12, choices=[('undecided', 'Not decided'), ('school', 'School lunch'), ('pack', 'Pack lunch'), ('none', 'No school')], default='undecided')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['child', 'date'], name='one_lunch_per_child_date')]

class ParentInvitation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    email = models.EmailField()
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True)

class GoogleConnection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    subject = models.CharField(max_length=255)
    email = models.EmailField()
    encrypted_refresh_token = models.TextField()
    needs_reconnect = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    # Granted only by an explicit opt-in; lets the app manage calendars it created (calendar.app.created).
    can_write = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['household', 'subject'], name='one_google_account_per_household')]

class GoogleCalendar(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(GoogleConnection, on_delete=models.CASCADE, related_name='calendars')
    external_id = models.CharField(max_length=1024)
    name = models.CharField(max_length=255)
    access_role = models.CharField(max_length=30)
    visibility = models.CharField(max_length=10, choices=[('off', 'Not shared'), ('busy', 'Busy only'), ('details', 'Event details')], default='off')
    color = models.CharField(max_length=12, default='blue')
    last_synced = models.DateTimeField(null=True)
    sync_error = models.CharField(max_length=255, blank=True)
    window_start = models.DateField(null=True)
    window_end = models.DateField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['connection', 'external_id'], name='one_calendar_per_connection')]

class FamilyCalendar(models.Model):
    """The one app-created Google calendar a household writes activities to."""
    household = models.OneToOneField(Household, on_delete=models.CASCADE, related_name='family_calendar')
    calendar = models.OneToOneField(GoogleCalendar, on_delete=models.CASCADE, related_name='family_for')
    created_at = models.DateTimeField(auto_now_add=True)

class GooglePendingDeletion(models.Model):
    """A Google event whose local activity was deleted but whose Google copy is not yet removed."""
    calendar = models.ForeignKey(GoogleCalendar, on_delete=models.CASCADE, related_name='pending_deletions')
    event_id = models.CharField(max_length=1024)
    title = models.CharField(max_length=200)
    error = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class GoogleEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    calendar = models.ForeignKey(GoogleCalendar, on_delete=models.CASCADE, related_name='events')
    external_id = models.CharField(max_length=1024)
    title = models.CharField(max_length=500)
    start_date = models.DateField()
    end_date = models.DateField()
    start_time = models.TimeField(null=True)
    end_time = models.TimeField(null=True)
    all_day = models.BooleanField(default=False)
    location = models.CharField(max_length=1000, blank=True)
    html_link = models.URLField(max_length=2048, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['calendar', 'external_id'], name='one_event_per_calendar')]
        ordering = ['start_date', 'start_time', 'title']

class AssistantPlan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.UUIDField(unique=True)
    title = models.CharField(max_length=200)
    messages = models.JSONField(default=list)
    reply = models.TextField(blank=True)
    questions = models.JSONField(default=list)
    status = models.CharField(max_length=12, default='generating')
    error = models.CharField(max_length=300, blank=True)
    revision = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class AssistantSuggestion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(AssistantPlan, on_delete=models.CASCADE, related_name='suggestions')
    revision = models.PositiveIntegerField()
    kind = models.CharField(max_length=10, choices=[('event', 'Event'), ('task', 'Task')])
    position = models.PositiveIntegerField()
    status = models.CharField(max_length=12, default='pending', choices=[('pending', 'Awaiting approval'), ('approved', 'Approved'), ('dismissed', 'Dismissed'), ('superseded', 'Earlier draft')])
    payload = models.JSONField()
    activity = models.ForeignKey(Activity, null=True, on_delete=models.SET_NULL)
    task = models.ForeignKey(Task, null=True, on_delete=models.SET_NULL)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    decided_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ['position', 'id']

class AssistantUsage(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    date = models.DateField()
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['household', 'date'], name='one_ai_usage_per_household_day')]

class ListTemplate(models.Model):
    """A reusable checklist, such as "Swim bag", that can be added to activities and tasks."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    items = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

class ChecklistItem(models.Model):
    """One line of a checklist on an activity or a task. On a repeating activity, done_dates holds
    the occurrence dates (ISO) where it was ticked; otherwise done_at records the tick."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    activity = models.ForeignKey(Activity, null=True, blank=True, on_delete=models.CASCADE, related_name='checklist_items')
    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.CASCADE, related_name='checklist_items')
    text = models.CharField(max_length=200)
    position = models.PositiveIntegerField(default=0)
    done_at = models.DateTimeField(null=True, blank=True)
    done_dates = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['position', 'text']
        constraints = [models.CheckConstraint(condition=models.Q(activity__isnull=False, task__isnull=True) | models.Q(activity__isnull=True, task__isnull=False), name='checklist_item_has_one_owner')]

class PushSubscription(models.Model):
    """A phone or browser that turned on reminders (REM-01). Every parent device in the household
    receives the household's reminders. Endpoint and keys come from the browser's push service."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    endpoint = models.TextField(unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    label = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)

class ReminderDelivery(models.Model):
    """One reminder to one device. The unique key makes each reminder send at most once per device;
    a failed send is retried on later runs (up to MAX_ATTEMPTS) while the reminder is still due."""
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    subscription = models.ForeignKey(PushSubscription, on_delete=models.CASCADE, related_name='deliveries')
    key = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['subscription', 'key'], name='one_delivery_per_device_reminder')]
