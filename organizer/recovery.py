import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import (Activity, AssistantPlan, AssistantSuggestion, ChecklistItem, FamilyMember, ListTemplate,
                     LunchPlan, Membership, SetupRecord, Task)
from .recurrence import validate_rule

FORMAT = 'home-headquarters'
MAX_ROWS = 20000
MAX_BYTES = 10 * 1024 * 1024

# Version 2 covers all household-owned organizer data. Accounts, memberships, invitations,
# Google connections/tokens/event caches, usage counters and recovery points are excluded.
COLLECTIONS = {
    'notes': {'title': str, 'created_at': str},
    'members': {'id': str, 'name': str, 'role': str, 'color': str, 'archived': bool},
    'activities': {'id': str, 'title': str, 'start_date': str, 'end_date': str, 'start_time': (str, type(None)),
                   'end_time': (str, type(None)), 'all_day': bool, 'timezone': str, 'location': str, 'notes': str,
                   'participants': list, 'reminder_minutes': (int, type(None)), 'recurrence': str, 'recurrence_exdates': list,
                   'series': (str, type(None)), 'occurrence_date': (str, type(None)), 'checklist': list},
    'tasks': {'id': str, 'title': str, 'high_priority': bool, 'assignee': (str, type(None)), 'activity': (str, type(None)),
              'due_date': (str, type(None)), 'due_time': (str, type(None)), 'notes': str, 'completed_at': (str, type(None)),
              'reminder_minutes': (int, type(None)), 'search_prompt': str, 'search_questions': str, 'recurrence': str,
              'recurrence_start': (str, type(None)), 'series_key': (str, type(None)), 'checklist': list},
    'lunches': {'child': str, 'date': str, 'choice': str},
    'assistant_plans': {'id': str, 'title': str, 'created_by': (str, type(None)), 'messages': list, 'reply': str,
                        'questions': list, 'status': str, 'error': str, 'revision': int, 'created_at': str,
                        'suggestions': list},
    'list_templates': {'name': str, 'items': list},
}
# Version 4 adds saved lists and checklist items on activities and tasks.
CHECKLIST = {'text': str, 'position': int, 'done_at': (str, type(None)), 'done_dates': list}
MAX_CHECKLIST = 50
# Version 2 predates recurrence; its rows are upgraded with these defaults before validation.
V2_DEFAULTS = {'activities': {'recurrence': '', 'recurrence_exdates': [], 'series': None, 'occurrence_date': None},
               'tasks': {'recurrence': '', 'recurrence_start': None, 'series_key': None}}
SUGGESTION = {'revision': int, 'kind': str, 'position': int, 'status': str, 'payload': dict,
              'activity': (str, type(None)), 'task': (str, type(None)), 'decided_by': (str, type(None)),
              'decided_at': (str, type(None))}

def iso(value):
    return value.isoformat() if value else None

def snapshot(household):
    members = FamilyMember.objects.filter(household=household).order_by('name', 'id')
    activities = Activity.objects.filter(household=household).prefetch_related('participants', 'checklist_items').order_by('start_date', 'start_time', 'id')
    tasks = Task.objects.filter(household=household).prefetch_related('checklist_items').order_by('due_date', 'title', 'id')
    plans = AssistantPlan.objects.filter(household=household).select_related('created_by').prefetch_related('suggestions__decided_by').order_by('created_at', 'id')
    return {
        'format': FORMAT, 'version': 4, 'scope': 'household', 'exported_at': timezone.now().isoformat(),
        'household': {'name': household.name, 'timezone': household.timezone},
        'notes': [{'title': x.title, 'created_at': iso(x.created_at)} for x in SetupRecord.objects.filter(household=household).order_by('created_at', 'id')],
        'members': [{'id': str(x.id), 'name': x.name, 'role': x.role, 'color': x.color, 'archived': x.archived} for x in members],
        'activities': [{
            'id': str(x.id), 'title': x.title, 'start_date': iso(x.start_date), 'end_date': iso(x.end_date),
            'start_time': iso(x.start_time), 'end_time': iso(x.end_time), 'all_day': x.all_day, 'timezone': x.timezone,
            'location': x.location, 'notes': x.notes, 'participants': sorted(str(p.id) for p in x.participants.all()),
            'reminder_minutes': x.reminder_minutes, 'recurrence': x.recurrence, 'recurrence_exdates': sorted(x.recurrence_exdates),
            'series': str(x.series_id) if x.series_id else None, 'occurrence_date': iso(x.occurrence_date),
            'checklist': checklist(x)} for x in activities],
        'tasks': [{
            'id': str(x.id), 'title': x.title, 'high_priority': x.high_priority,
            'assignee': str(x.assignee_id) if x.assignee_id else None, 'activity': str(x.activity_id) if x.activity_id else None,
            'due_date': iso(x.due_date), 'due_time': iso(x.due_time), 'notes': x.notes, 'completed_at': iso(x.completed_at),
            'reminder_minutes': x.reminder_minutes, 'search_prompt': x.search_prompt, 'search_questions': x.search_questions,
            'recurrence': x.recurrence, 'recurrence_start': iso(x.recurrence_start), 'series_key': str(x.series_key) if x.series_key else None,
            'checklist': checklist(x)} for x in tasks],
        'lunches': [{'child': str(x.child_id), 'date': iso(x.date), 'choice': x.choice}
                    for x in LunchPlan.objects.filter(household=household).order_by('date', 'child_id')],
        'assistant_plans': [{
            'id': str(x.id), 'title': x.title, 'created_by': x.created_by.username, 'messages': x.messages, 'reply': x.reply,
            'questions': x.questions, 'status': x.status, 'error': x.error, 'revision': x.revision, 'created_at': iso(x.created_at),
            'suggestions': [{
                'revision': s.revision, 'kind': s.kind, 'position': s.position, 'status': s.status, 'payload': s.payload,
                'activity': str(s.activity_id) if s.activity_id else None, 'task': str(s.task_id) if s.task_id else None,
                'decided_by': s.decided_by.username if s.decided_by else None, 'decided_at': iso(s.decided_at)}
                for s in sorted(x.suggestions.all(), key=lambda s: (s.revision, s.position, str(s.id)))]} for x in plans],
        'list_templates': [{'name': x.name, 'items': x.items} for x in ListTemplate.objects.filter(household=household).order_by('name', 'id')],
    }

def checklist(owner):
    return [{'text': item.text, 'position': item.position, 'done_at': iso(item.done_at), 'done_dates': sorted(item.done_dates)}
            for item in sorted(owner.checklist_items.all(), key=lambda item: (item.position, item.text, str(item.id)))]

def check_row(row, spec, label):
    if not isinstance(row, dict) or set(row) != set(spec):
        raise ValidationError(f'{label} has missing or unexpected fields.')
    for key, kinds in spec.items():
        # bool is a subclass of int; reject it where a number is expected.
        if not isinstance(row[key], kinds) or (isinstance(row[key], bool) and bool not in (kinds if isinstance(kinds, tuple) else (kinds,))):
            raise ValidationError(f'{label} has an invalid {key.replace("_", " ")}.')

def check_model(instance, exclude, label):
    try:
        instance.full_clean(exclude=exclude, validate_unique=False, validate_constraints=False)
    except ValidationError as error:
        field = next(iter(error.message_dict), 'value') if hasattr(error, 'message_dict') else 'value'
        raise ValidationError(f'{label} has an invalid {field.replace("_", " ")}.')

def stamp(value, label):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValidationError(f'{label} has an invalid date or time.')
    if parsed.tzinfo is None:
        raise ValidationError(f'{label} has a date and time without a time zone.')
    return parsed

def check_zone(value, label):
    try:
        ZoneInfo(value)
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        raise ValidationError(f'{label} has an invalid time zone.')

def validate_header(data):
    if not isinstance(data, dict) or data.get('format') != FORMAT:
        raise ValidationError('This is not a supported household export.')
    version = data.get('version')
    if type(version) is not int or version not in (1, 2, 3, 4):
        raise ValidationError('This export version is not supported.')
    household = data.get('household')
    if not isinstance(household, dict) or set(household) != {'name', 'timezone'}:
        raise ValidationError('Household information is invalid.')
    name = household['name']
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ValidationError('Household name is invalid.')
    check_zone(household['timezone'], 'The export')
    if not isinstance(data.get('exported_at'), str):
        raise ValidationError('Export date or time zone is invalid.')
    try:
        stamp(data['exported_at'], 'The export')
    except ValidationError:
        raise ValidationError('Export date or time zone is invalid.')
    return version

def validate_snapshot(data):
    """Validate a version 1 notes-only export and return its note rows."""
    if validate_header(data) != 1 or set(data) != {'format', 'version', 'scope', 'exported_at', 'household', 'records'} or data['scope'] != 'foundation':
        raise ValidationError('This is not a supported version 1 notes export.')
    if not isinstance(data['records'], list) or len(data['records']) > 1000:
        raise ValidationError('An export can contain at most 1,000 foundation records.')
    for row in data['records']:
        if not isinstance(row, dict) or set(row) != {'title'} or not isinstance(row['title'], str) or not 1 <= len(row['title'].strip()) <= 200:
            raise ValidationError('A record has an invalid title.')
    return data['records']

def upgrade(data):
    """Return a version 4 copy of a version 2 or 3 export; other data is returned unchanged."""
    if not isinstance(data, dict) or data.get('version') not in (2, 3):
        return data
    if data['version'] == 2:
        data = dict(data, version=3)
        for name, defaults in V2_DEFAULTS.items():
            if isinstance(data.get(name), list):
                data[name] = [defaults | row if isinstance(row, dict) and not set(defaults) & set(row) else row for row in data[name]]
    # Version 3 predates saved lists and checklists.
    data = dict(data, version=4)
    for name in ('activities', 'tasks'):
        if isinstance(data.get(name), list):
            data[name] = [dict(row, checklist=[]) if isinstance(row, dict) and 'checklist' not in row else row for row in data[name]]
    data.setdefault('list_templates', [])
    return data

def validate_household(data):
    """Validate a version 2, 3 or 4 export completely, including every cross-reference, before any write.

    Returns the export upgraded to version 4."""
    version = validate_header(data)
    data = upgrade(data)
    if version not in (2, 3, 4) or set(data) != {'format', 'version', 'scope', 'exported_at', 'household', *COLLECTIONS} or data['scope'] != 'household':
        raise ValidationError('This is not a supported household export.')
    for name, spec in COLLECTIONS.items():
        if not isinstance(data[name], list) or len(data[name]) > MAX_ROWS:
            raise ValidationError(f'The export has an invalid {name.replace("_", " ")} list.')
        for row in data[name]:
            check_row(row, spec, f'A {name[:-1].replace("_", " ")} entry')

    def unique_ids(rows, label):
        ids = [row['id'] for row in rows]
        if len(set(ids)) != len(ids):
            raise ValidationError(f'The export repeats a {label} identifier.')
        return set(ids)

    for row in data['notes']:
        check_model(SetupRecord(title=row['title']), ['household'], 'A note')
        stamp(row['created_at'], 'A note')
    members = unique_ids(data['members'], 'family member')
    children = {row['id'] for row in data['members'] if row['role'] == 'child'}
    for row in data['members']:
        check_model(FamilyMember(**{k: v for k, v in row.items() if k != 'id'}), ['household'], 'A family member')
    activities = unique_ids(data['activities'], 'activity')
    series_rows = {row['id']: row for row in data['activities'] if row['recurrence']}
    overrides = set()
    for row in data['activities']:
        values = {k: v for k, v in row.items() if k not in ('id', 'participants', 'series', 'recurrence_exdates', 'checklist')}
        item = Activity(**values)
        check_checklist(row['checklist'], 'An activity')
        check_model(item, ['household'], 'An activity')
        check_zone(row['timezone'], 'An activity')
        if item.end_date < item.start_date:
            raise ValidationError('An activity ends before it starts.')
        if row['recurrence']:
            validate_rule(row['recurrence'], item.start_date)
        dates = row['recurrence_exdates']
        try:
            if any(not isinstance(value, str) or date.fromisoformat(value).isoformat() != value for value in dates) or len(set(dates)) != len(dates):
                raise ValueError
        except ValueError:
            raise ValidationError('An activity has an invalid skipped date.')
        if row['series'] is not None:
            parent = series_rows.get(row['series'])
            if parent is None or parent['series'] is not None or row['recurrence'] or not item.occurrence_date:
                raise ValidationError('A changed occurrence refers to a repeating activity that is not in the export.')
            if (row['series'], item.occurrence_date) in overrides:
                raise ValidationError('The export changes the same occurrence twice.')
            overrides.add((row['series'], item.occurrence_date))
        elif item.occurrence_date:
            raise ValidationError('An activity has an occurrence date without a repeating activity.')
        refs = row['participants']
        if any(not isinstance(ref, str) for ref in refs) or len(set(refs)) != len(refs) or not set(refs) <= members:
            raise ValidationError('An activity refers to a family member that is not in the export.')
    tasks = unique_ids(data['tasks'], 'task')
    series_dates = set()
    for row in data['tasks']:
        values = {k: v for k, v in row.items() if k not in ('id', 'assignee', 'activity', 'completed_at', 'checklist')}
        task = Task(**values)
        check_checklist(row['checklist'], 'A task')
        check_model(task, ['household', 'assignee', 'activity'], 'A task')
        if row['completed_at']:
            stamp(row['completed_at'], 'A task')
        if row['recurrence']:
            if not (task.recurrence_start and task.due_date and task.series_key):
                raise ValidationError('A repeating task is missing its due date or series.')
            validate_rule(row['recurrence'], task.recurrence_start)
        if task.series_key:
            if (task.series_key, task.due_date) in series_dates:
                raise ValidationError('The export repeats a task in the same series and date.')
            series_dates.add((task.series_key, task.due_date))
        if row['assignee'] and row['assignee'] not in members or row['activity'] and row['activity'] not in activities:
            raise ValidationError('A task refers to a family member or activity that is not in the export.')
    lunch_days = set()
    for row in data['lunches']:
        lunch = LunchPlan(date=row['date'], choice=row['choice'])
        check_model(lunch, ['household', 'child'], 'A lunch plan')
        if row['child'] not in children:
            raise ValidationError('A lunch plan refers to a child who is not in the export.')
        if (row['child'], lunch.date) in lunch_days:
            raise ValidationError('The export has two lunch plans for the same child and date.')
        lunch_days.add((row['child'], lunch.date))
    unique_ids(data['assistant_plans'], 'assistant plan')
    suggestions = 0
    for row in data['assistant_plans']:
        values = {k: v for k, v in row.items() if k not in ('id', 'created_by', 'created_at', 'suggestions')}
        check_model(AssistantPlan(request_key=uuid.uuid4(), **values), ['household', 'created_by', 'messages', 'questions'], 'An assistant plan')
        stamp(row['created_at'], 'An assistant plan')
        suggestions += len(row['suggestions'])
        if suggestions > MAX_ROWS:
            raise ValidationError('The export has too many assistant suggestions.')
        for item in row['suggestions']:
            check_row(item, SUGGESTION, 'An assistant suggestion')
            values = {k: v for k, v in item.items() if k not in ('activity', 'task', 'decided_by', 'decided_at')}
            check_model(AssistantSuggestion(**values), ['plan', 'activity', 'task', 'decided_by', 'decided_at', 'payload'], 'An assistant suggestion')
            if item['decided_at']:
                stamp(item['decided_at'], 'An assistant suggestion')
            if item['activity'] and item['activity'] not in activities or item['task'] and item['task'] not in tasks:
                raise ValidationError('An assistant suggestion refers to a plan that is not in the export.')
    for row in data['list_templates']:
        items = row['items']
        if not 1 <= len(row['name'].strip()) <= 100 or not 1 <= len(items) <= MAX_CHECKLIST or \
                any(not isinstance(text, str) or not 1 <= len(text.strip()) <= 200 for text in items):
            raise ValidationError('A saved list has an invalid name or items.')
    return data

def check_checklist(items, label):
    if len(items) > MAX_CHECKLIST:
        raise ValidationError(f'{label} has too many checklist items.')
    for item in items:
        check_row(item, CHECKLIST, f'{label} checklist item')
        if not 1 <= len(item['text'].strip()) <= 200 or item['position'] < 0:
            raise ValidationError(f'{label} has an invalid checklist item.')
        if item['done_at']:
            stamp(item['done_at'], f'{label} checklist item')
        dates = item['done_dates']
        try:
            if any(not isinstance(value, str) or date.fromisoformat(value).isoformat() != value for value in dates) or len(set(dates)) != len(dates):
                raise ValueError
        except ValueError:
            raise ValidationError(f'{label} checklist item has an invalid date.')

def summarize(data):
    if data['version'] == 1:
        return {'notes': len(data['records'])}
    return {name: len(data[name]) for name in COLLECTIONS} | {
        'assistant_suggestions': sum(len(row['suggestions']) for row in data['assistant_plans']),
        'checklist_items': sum(len(row['checklist']) for row in data['activities'] + data['tasks'])}

def validate_any(data):
    """Validate either supported export version and return its row counts."""
    if isinstance(data, dict) and data.get('version') == 1:
        validate_snapshot(data)
        return summarize(data)
    return summarize(validate_household(data))

def remap_payload(payload, members):
    payload = dict(payload)
    if isinstance(payload.get('participants'), list):
        payload['participants'] = [members[ref] for ref in payload['participants'] if isinstance(ref, str) and ref in members]
    if 'assignee' in payload:
        payload['assignee'] = members.get(payload['assignee']) if isinstance(payload['assignee'], str) else None
    return payload

def replace_household_data(household, user, data):
    """Replace organizer data in an already-locked household. Callers save a recovery point first.

    Version 1 exports replace notes only. Version 2 exports replace all organizer data with newly
    generated identifiers, rewiring every reference, so an export can be restored into the same
    household or into a separate one without identifier collisions.
    """
    if data['version'] == 1:
        rows = validate_snapshot(data)
        SetupRecord.objects.filter(household=household).delete()
        SetupRecord.objects.bulk_create([SetupRecord(household=household, title=row['title']) for row in rows])
        return
    data = validate_household(data)
    # A restore replaces local data only; it never edits or deletes the family Google calendar.
    from .google_writes import paused
    token = paused.set(True)
    try:
        replace_validated(household, user, data)
    finally:
        paused.reset(token)

def replace_validated(household, user, data):
    AssistantPlan.objects.filter(household=household).delete()
    Task.objects.filter(household=household).delete()
    LunchPlan.objects.filter(household=household).delete()
    Activity.objects.filter(household=household).delete()
    FamilyMember.objects.filter(household=household).delete()
    SetupRecord.objects.filter(household=household).delete()
    ListTemplate.objects.filter(household=household).delete()

    notes = SetupRecord.objects.bulk_create([SetupRecord(household=household, title=row['title']) for row in data['notes']])
    for note, row in zip(notes, data['notes']):
        SetupRecord.objects.filter(pk=note.pk).update(created_at=stamp(row['created_at'], 'A note'))
    members = {}
    for row in data['members']:
        members[row['id']] = FamilyMember(household=household, **{k: v for k, v in row.items() if k != 'id'})
    FamilyMember.objects.bulk_create(members.values())
    activities, links = {}, []
    # Series before their changed occurrences, so each override can point at its new series ID.
    for row in sorted(data['activities'], key=lambda row: row['series'] is not None):
        item = Activity(household=household, series=activities.get(row['series']),
                        **{k: v for k, v in row.items() if k not in ('id', 'participants', 'series', 'checklist')})
        activities[row['id']] = item
        links.extend((item, members[ref]) for ref in row['participants'])
    Activity.objects.bulk_create([item for item in activities.values() if item.series is None])
    Activity.objects.bulk_create([item for item in activities.values() if item.series is not None])
    Through = Activity.participants.through
    Through.objects.bulk_create([Through(activity_id=a.pk, familymember_id=m.pk) for a, m in links])
    tasks, series_keys = {}, {}
    for row in data['tasks']:
        values = {k: v for k, v in row.items() if k not in ('id', 'assignee', 'activity', 'completed_at', 'series_key', 'checklist')}
        # New series keys keep repeating-task uniqueness when restoring beside the original household.
        key = series_keys.setdefault(row['series_key'], uuid.uuid4()) if row['series_key'] else None
        tasks[row['id']] = Task(household=household, assignee=members.get(row['assignee']), activity=activities.get(row['activity']),
                                completed_at=stamp(row['completed_at'], 'A task') if row['completed_at'] else None, series_key=key, **values)
    Task.objects.bulk_create(tasks.values())
    items = []
    for kind, owners, rows in (('activity', activities, data['activities']), ('task', tasks, data['tasks'])):
        for row in rows:
            items += [ChecklistItem(household=household, text=item['text'], position=item['position'], done_dates=item['done_dates'],
                                    done_at=stamp(item['done_at'], 'A checklist item') if item['done_at'] else None, **{kind: owners[row['id']]})
                      for item in row['checklist']]
    ChecklistItem.objects.bulk_create(items)
    ListTemplate.objects.bulk_create([ListTemplate(household=household, name=row['name'], items=row['items']) for row in data['list_templates']])
    LunchPlan.objects.bulk_create([LunchPlan(household=household, child=members[row['child']], date=row['date'], choice=row['choice'])
                                   for row in data['lunches']])
    parents = {m.user.username.lower(): m.user for m in Membership.objects.filter(household=household, active=True).select_related('user')}
    new_ids = {key: str(item.pk) for key, item in members.items()}
    for row in data['assistant_plans']:
        values = {k: v for k, v in row.items() if k not in ('id', 'created_by', 'created_at', 'suggestions')}
        plan = AssistantPlan.objects.create(household=household, request_key=uuid.uuid4(),
                                            created_by=parents.get((row['created_by'] or '').lower(), user), **values)
        AssistantPlan.objects.filter(pk=plan.pk).update(created_at=stamp(row['created_at'], 'An assistant plan'))
        AssistantSuggestion.objects.bulk_create([AssistantSuggestion(
            plan=plan, revision=item['revision'], kind=item['kind'], position=item['position'], status=item['status'],
            payload=remap_payload(item['payload'], new_ids), activity=activities.get(item['activity']), task=tasks.get(item['task']),
            decided_by=parents.get((item['decided_by'] or '').lower()),
            decided_at=stamp(item['decided_at'], 'An assistant suggestion') if item['decided_at'] else None)
            for item in row['suggestions']])
