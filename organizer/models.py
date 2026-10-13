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

    class Meta:
        ordering = ['start_date', 'start_time', 'title']

    def __str__(self):
        return self.title

class Task(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    assignee = models.ForeignKey(FamilyMember, null=True, blank=True, on_delete=models.SET_NULL)
    activity = models.ForeignKey(Activity, null=True, blank=True, on_delete=models.SET_NULL, related_name='tasks')
    due_date = models.DateField(null=True, blank=True)
    due_time = models.TimeField(null=True, blank=True)
    notes = models.TextField(max_length=5000, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['due_date', 'title']

class LunchPlan(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE)
    child = models.ForeignKey(FamilyMember, on_delete=models.CASCADE)
    date = models.DateField()
    choice = models.CharField(max_length=12, choices=[('undecided', 'Not decided'), ('school', 'School lunch'), ('pack', 'Pack lunch'), ('none', 'No school')], default='undecided')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['child', 'date'], name='one_lunch_per_child_date')]
