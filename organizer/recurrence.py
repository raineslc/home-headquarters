"""Local recurrence for activities and tasks.

Rules are RFC 5545 RRULE strings (no DTSTART) anchored on a local date. Times are wall-clock
times in the activity's zone. Clock changes follow the owner's Option A (matching Google
Calendar): a time skipped by spring-forward moves forward by the gap (2:30 becomes 3:30), and
a repeated fall-back time uses its first occurrence.
"""
from datetime import datetime, timedelta, timezone as utc_timezone
from zoneinfo import ZoneInfo
from dateutil.rrule import rrulestr, DAILY, WEEKLY, MONTHLY, YEARLY
from django.core.exceptions import ValidationError

FREQUENCIES = {'DAILY': DAILY, 'WEEKLY': WEEKLY, 'MONTHLY': MONTHLY, 'YEARLY': YEARLY}
WEEKDAYS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']
WEEKDAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
ORDINALS = {1: 'first', 2: 'second', 3: 'third', 4: 'fourth', -1: 'last'}
ALLOWED_PARTS = {'FREQ', 'INTERVAL', 'BYDAY', 'BYMONTHDAY', 'UNTIL', 'COUNT'}
MAX_COUNT = 500

def parse_parts(rule):
    parts = {}
    for piece in rule.split(';'):
        key, sep, value = piece.partition('=')
        if not sep or key not in ALLOWED_PARTS or key in parts or not value:
            raise ValidationError('This repeat rule is not supported.')
        parts[key] = value
    if parts.get('FREQ') not in FREQUENCIES or ('UNTIL' in parts and 'COUNT' in parts):
        raise ValidationError('This repeat rule is not supported.')
    return parts

def validate_rule(rule, anchor, check_anchor=True):
    """Check a stored rule (from a form or an export) and return it unchanged."""
    if not isinstance(rule, str) or len(rule) > 300:
        raise ValidationError('This repeat rule is not supported.')
    parts = parse_parts(rule)
    try:
        interval = int(parts.get('INTERVAL', '1'))
        count = int(parts['COUNT']) if 'COUNT' in parts else None
        until = datetime.strptime(parts['UNTIL'], '%Y%m%d').date() if 'UNTIL' in parts else None
        rrulestr(rule, dtstart=datetime.combine(anchor, datetime.min.time()))
    except (ValueError, TypeError):
        raise ValidationError('This repeat rule is not supported.')
    if not 1 <= interval <= 99 or count is not None and not 1 <= count <= MAX_COUNT:
        raise ValidationError('Repeat every 1–99 periods, up to 500 times.')
    if until and until < anchor:
        raise ValidationError('The repeat end date cannot be before the first date.')
    if check_anchor and not dates_between(rule, anchor, anchor, anchor):
        # The anchor must itself be an occurrence, or series splits could leave a stray date behind.
        raise ValidationError('The first date must match the repeat pattern, such as one of the chosen weekdays.')
    return rule

def build_rule(freq, interval, anchor, weekdays=(), monthly_by='day', ends='never', until=None, count=None, check_anchor=True):
    parts = [f'FREQ={freq}']
    if interval and interval != 1:
        parts.append(f'INTERVAL={interval}')
    if freq == 'WEEKLY':
        days = [d for d in WEEKDAYS if d in weekdays] or [WEEKDAYS[anchor.weekday()]]
        parts.append('BYDAY=' + ','.join(days))
    elif freq == 'MONTHLY':
        if monthly_by == 'weekday':
            nth = (anchor.day - 1) // 7 + 1
            parts.append(f'BYDAY={-1 if nth == 5 else nth}{WEEKDAYS[anchor.weekday()]}')
        else:
            parts.append(f'BYMONTHDAY={anchor.day}')
    if ends == 'until' and until:
        parts.append('UNTIL=' + until.strftime('%Y%m%d'))
    elif ends == 'count' and count:
        parts.append(f'COUNT={count}')
    return validate_rule(';'.join(parts), anchor, check_anchor)

def rule_fields(rule):
    """Form initial values for a stored rule."""
    if not rule:
        return {'repeat': '', 'interval': 1, 'ends': 'never'}
    parts = parse_parts(rule)
    days = parts.get('BYDAY', '')
    values = {'repeat': parts['FREQ'], 'interval': int(parts.get('INTERVAL', '1')), 'ends': 'never',
              'weekdays': [d for d in days.split(',') if d in WEEKDAYS] if parts['FREQ'] == 'WEEKLY' else [],
              'monthly_by': 'weekday' if parts['FREQ'] == 'MONTHLY' and days else 'day'}
    if 'UNTIL' in parts:
        values.update(ends='until', until=datetime.strptime(parts['UNTIL'], '%Y%m%d').date())
    elif 'COUNT' in parts:
        values.update(ends='count', count=int(parts['COUNT']))
    return values

def describe(rule, anchor):
    if not rule:
        return ''
    parts = parse_parts(rule)
    interval = int(parts.get('INTERVAL', '1'))
    unit = {'DAILY': 'day', 'WEEKLY': 'week', 'MONTHLY': 'month', 'YEARLY': 'year'}[parts['FREQ']]
    text = f'Every {unit}' if interval == 1 else f'Every {interval} {unit}s'
    if parts['FREQ'] == 'DAILY' and interval == 1:
        text = 'Daily'
    if parts['FREQ'] == 'WEEKLY':
        names = [WEEKDAY_NAMES[WEEKDAYS.index(d)] for d in parts.get('BYDAY', '').split(',') if d in WEEKDAYS]
        text += ' on ' + ', '.join(names)
    elif parts['FREQ'] == 'MONTHLY':
        if 'BYDAY' in parts:
            day = parts['BYDAY']
            text += f' on the {ORDINALS.get(int(day[:-2]), day[:-2])} {WEEKDAY_NAMES[WEEKDAYS.index(day[-2:])]}'
        else:
            text += f' on day {parts["BYMONTHDAY"]}'
    elif parts['FREQ'] == 'YEARLY':
        text += anchor.strftime(' on %B ') + str(anchor.day)
    if 'UNTIL' in parts:
        until = datetime.strptime(parts['UNTIL'], '%Y%m%d').date()
        text += f', until {until:%b} {until.day}, {until.year}'
    elif 'COUNT' in parts:
        text += f', {parts["COUNT"]} times'
    return text

def dates_between(rule, anchor, start, end):
    """Occurrence start dates of a rule anchored on `anchor`, within [start, end] inclusive."""
    if end < start:
        return []
    series = rrulestr(rule, dtstart=datetime.combine(anchor, datetime.min.time()))
    return [moment.date() for moment in series.between(datetime.combine(start, datetime.min.time()),
                                                        datetime.combine(end, datetime.min.time()), inc=True)]

def is_occurrence(rule, anchor, day):
    return bool(rule) and day in dates_between(rule, anchor, day, day)

def next_date(rule, anchor, after):
    """The first occurrence strictly after `after`, or None when the series has ended."""
    series = rrulestr(rule, dtstart=datetime.combine(anchor, datetime.min.time()))
    following = series.after(datetime.combine(after, datetime.min.time()), inc=False)
    return following.date() if following else None

def first_on_or_after(rule, day):
    """The first date on or after `day` that matches the rule's pattern when anchored there."""
    return next_date(rule, day, day - timedelta(days=1))

def end_before(rule, anchor, day):
    """The rule truncated so its last occurrence is before `day`, or '' if none would remain."""
    earlier = dates_between(rule, anchor, anchor, day - timedelta(days=1))
    if not earlier:
        return ''
    parts = [p for p in rule.split(';') if not p.startswith(('UNTIL=', 'COUNT='))]
    return ';'.join(parts + ['UNTIL=' + earlier[-1].strftime('%Y%m%d')])

def wall_time(day, value, zone_name):
    """Apply Option A to a local wall time: skipped times move forward; repeated times use the first."""
    if value is None:
        return day, None
    zone = ZoneInfo(zone_name)
    naive = datetime.combine(day, value)
    actual = naive.replace(tzinfo=zone, fold=0).astimezone(utc_timezone.utc).astimezone(zone)
    return actual.date(), actual.time().replace(tzinfo=None)

class Occurrence:
    """One dated instance of a repeating Activity, shaped like an Activity for templates."""
    def __init__(self, activity, day):
        self.activity = activity
        self.instance_date = day
        span = activity.end_date - activity.start_date
        self.start_date, self.start_time = wall_time(day, activity.start_time, activity.timezone)
        self.end_date, self.end_time = wall_time(day + span, activity.end_time, activity.timezone)

    def __getattr__(self, name):
        return getattr(self.activity, name)

    @property
    def detail_query(self):
        return '?occurrence=' + self.instance_date.isoformat()

def occurrence_of(activity, day):
    if activity.recurrence and day.isoformat() not in activity.recurrence_exdates and is_occurrence(activity.recurrence, activity.start_date, day):
        return Occurrence(activity, day)
    return None

def expand(activities, start, end):
    """Expand a queryset of household activities into events overlapping [start, end]."""
    events = []
    for activity in activities:
        if not activity.recurrence:
            if activity.start_date <= end and activity.end_date >= start:
                events.append(activity)
            continue
        skipped = set(activity.recurrence_exdates)
        span = activity.end_date - activity.start_date
        for day in dates_between(activity.recurrence, activity.start_date, start - span, end):
            if day.isoformat() not in skipped:
                events.append(Occurrence(activity, day))
    return events

def household_events(household, start, end):
    from django.db.models import Q
    from .models import Activity
    query = Activity.objects.filter(household=household).filter(
        Q(recurrence='', start_date__lte=end, end_date__gte=start) | (~Q(recurrence='') & Q(start_date__lte=end))
    ).prefetch_related('participants')
    return expand(query, start, end)
