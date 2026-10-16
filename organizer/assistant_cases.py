"""Assistant regression cases (AI-04).

Each case is a planning request with a fixed "today" and family, plus checks on the validated
proposal a parent would review. The same cases run two ways:

- In the test suite against recorded sample outputs (no network), so the checks and the
  server-side validation are exercised on every change.
- Against the real provider with `python manage.py assistant_eval` (opt-in, uses API credit),
  inside a transaction that is rolled back, to catch model or instruction regressions.

Checks describe what the user should see, not exact wording, so different valid drafts pass.
"""
import re
from dataclasses import dataclass, field
from datetime import date

FAMILY = [('Alex', 'parent'), ('Sam', 'parent'), ('Logan', 'child'), ('Henry', 'child')]
WEDNESDAY = date(2026, 10, 14)
SATURDAY = date(2026, 10, 17)

def words(text):
    return re.sub(r'[^a-z0-9 ]', ' ', (text or '').lower())

def asks(result, *patterns):
    """True when any question matches all the given regex patterns."""
    return any(all(re.search(p, words(q)) for p in patterns) for q in result['questions'])

def task_titles(result):
    return [words(task['title']) for task in result['tasks']]

@dataclass
class Case:
    name: str
    request: str
    today: date
    checks: list
    # Earlier conversation and drafts for clarification cases. '{Name}' in drafts becomes a member ID.
    history: list = field(default_factory=list)
    drafts: list = field(default_factory=list)

    def turns(self):
        return self.history + [{'role': 'user', 'text': self.request}]

def check(description):
    def wrap(function):
        function.description = description
        return function
    return wrap

# Checks applied to every case.
@check('Reply says nothing has been added')
def honest_reply(result, ids):
    return 'nothing has been added' in result['reply'].lower() or 'no activity or task could be drafted' in result['reply'].lower()

@check('No duplicate tasks or questions')
def no_duplicates(result, ids):
    titles, questions = task_titles(result), [words(q) for q in result['questions']]
    return len(set(titles)) == len(titles) and len(set(questions)) == len(questions)

@check('Search prompts contain no family names or email addresses')
def private_search(result, ids):
    names = [name.lower() for name, _ in FAMILY]
    return all('@' not in t['search_prompt'] and not any(re.search(r'\b' + n + r'\b', t['search_prompt'].lower()) for n in names)
               for t in result['tasks'])

@check('No high priority or reminders unless asked')
def no_unrequested_flags(result, ids):
    items = result['tasks'] + ([result['event']] if result['event'] else [])
    return not any(t.get('high_priority') for t in result['tasks']) and not any(i['reminder_minutes'] for i in items)

@check('Keeps the plan to a few tasks (at most 4)')
def few_tasks(result, ids):
    return len(result['tasks']) <= 4

COMMON = [honest_reply, no_duplicates, private_search, no_unrequested_flags, few_tasks]

def event_field(name, expected):
    @check(f'Activity {name} is {expected}')
    def test(result, ids):
        return bool(result['event']) and result['event'][name] == expected
    return test

@check('Activity title does not assume whose birthday it is')
def neutral_birthday_title(result, ids):
    return bool(result['event']) and 'logan s' not in words(result['event']['title']) and "logan's" not in result['event']['title'].lower()

@check('Logan is a participant')
def logan_attends(result, ids):
    return bool(result['event']) and ids['Logan'] in result['event']['participants']

@check('No task assumes the gift is for Logan')
def gift_not_for_logan(result, ids):
    return not any('logan' in title for title in task_titles(result))

@check('Asks whose birthday it is')
def asks_whose_birthday(result, ids):
    return asks(result, r'whose|who s|who is|birthday child|celebrat')

@check('Asks the recipient age and gift budget')
def asks_age_and_budget(result, ids):
    return asks(result, r'\bage\b|\bold\b|turning') and asks(result, r'budget|spend|\$|price')

@check('Proposes buying and wrapping a gift, and confirming the address')
def gift_tasks(result, ids):
    titles = ' | '.join(task_titles(result))
    return re.search(r'\b(buy|get|pick|choose|purchase)\b.*\bgift\b', titles) and 'wrap' in titles and 'address' in titles

@check('Buying and wrapping the gift are one task')
def gift_consolidated(result, ids):
    gift = [title for title in task_titles(result) if re.search(r'\b(buy|get|pick|choose|purchase|wrap)\b', title) and 'gift' in title]
    return len(gift) == 1 and 'wrap' in gift[0]


@check('End time is not invented (left empty and asked)')
def end_time_not_invented(result, ids):
    return bool(result['event']) and result['event']['end_time'] is None and asks(result, r'end')

@check('Asks which date when the weekday is today')
def same_day_question(result, ids):
    event = result['event']
    return (event is None or event['start_date'] is None or asks(result, r'today|this saturday|next saturday|which saturday|which date|confirm.*date|date'))

@check('No time, location or end invented from a one-word request')
def nothing_invented(result, ids):
    event = result['event']
    return event is None or (event['start_time'] is None and event['end_time'] is None and not event['location'])

@check('Asks for the missing date or time')
def asks_when(result, ids):
    return asks(result, r'date|when|day') or asks(result, r'time')

@check('Task-only request has no activity')
def no_event(result, ids):
    return result['event'] is None

def task_due(expected):
    @check(f'A task is due {expected}')
    def test(result, ids):
        return any(t['due_date'] == expected for t in result['tasks'])
    return test

def event_repeat(frequency, weekday=None, ends=None, until=None):
    @check(f'Activity repeats {frequency.lower()}' + (f' on {weekday}' if weekday else '') + (f' until {until}' if until else ''))
    def test(result, ids):
        event = result['event']
        return (bool(event) and event['repeat'] == frequency and (weekday is None or weekday in event['weekdays'])
                and (ends is None or event['ends'] == ends) and (until is None or event['until'] == until))
    return test

def task_repeat(frequency, weekday=None):
    @check(f'A task repeats {frequency.lower()}' + (f' on {weekday}' if weekday else ''))
    def test(result, ids):
        return any(t['repeat'] == frequency and (weekday is None or weekday in t['weekdays']) for t in result['tasks'])
    return test

@check('Repeating task starts on a matching Thursday from today')
def recycling_first_date(result, ids):
    return any(t['repeat'] and t['due_date'] and date.fromisoformat(t['due_date']).weekday() == 3
               and date.fromisoformat(t['due_date']) >= WEDNESDAY for t in result['tasks'])

@check('Keeps the parent’s edited task title')
def keeps_edit(result, ids):
    return any('book' in title for title in task_titles(result))

@check('Does not bring back the dismissed address task')
def dismissed_stays_dismissed(result, ids):
    return not any('address' in title for title in task_titles(result))

@check('Does not ask again for details already given')
def no_repeat_questions(result, ids):
    return not asks(result, r'whose|who s|who is') and not asks(result, r'budget') and not asks(result, r'\bage\b|how old')

BIRTHDAY = 'Logan has a birthday party Saturday at 2 PM. We need a gift.'

CASES = [
    Case('birthday_recipient', BIRTHDAY, WEDNESDAY, COMMON + [
        event_field('start_date', '2026-10-17'), event_field('start_time', '14:00:00'), neutral_birthday_title, logan_attends,
        gift_not_for_logan, asks_whose_birthday, asks_age_and_budget, gift_tasks, gift_consolidated, end_time_not_invented]),
    Case('same_day_weekday', 'Henry has a soccer game Saturday at 10 AM.', SATURDAY, COMMON + [same_day_question]),
    Case('sparse_input', 'soccer', WEDNESDAY, COMMON + [nothing_invented, asks_when]),
    Case('task_only', "Renew Henry's passport by November 30.", WEDNESDAY, COMMON + [no_event, task_due('2026-11-30')]),
    Case('repeating_activity', 'Henry has swim lessons every Tuesday at 4 PM, starting next week, until December 15. They last an hour.',
         WEDNESDAY, COMMON + [event_field('start_date', '2026-10-20'), event_field('start_time', '16:00:00'), event_field('end_time', '17:00:00'),
                              event_repeat('WEEKLY', 'TU', 'until', '2026-12-15')]),
    Case('repeating_task', 'Take out the recycling every Thursday evening.', WEDNESDAY, COMMON + [task_repeat('WEEKLY', 'TH'), recycling_first_date]),
    Case('clarification_keeps_edits', "It's Maya's birthday, she is turning 7, and our budget is $25. The party ends at 4 PM.", WEDNESDAY,
         COMMON + [event_field('end_time', '16:00:00'), keeps_edit, dismissed_stays_dismissed, no_repeat_questions],
         history=[{'role': 'user', 'text': BIRTHDAY},
                  {'role': 'assistant', 'text': 'Proposed activity: Birthday party. Date: 2026-10-17.',
                   'questions': ['Whose birthday is it?', 'How old will they be, and what is your gift budget?', 'What time does the activity end?']}],
         drafts=[{'kind': 'event', 'status': 'pending', 'payload': {'title': 'Birthday party', 'start_date': '2026-10-17', 'end_date': '2026-10-17',
                                                                   'start_time': '14:00:00', 'end_time': None, 'all_day': False, 'participants': ['{Logan}']}},
                 {'kind': 'task', 'status': 'pending', 'payload': {'title': 'Buy a book as a gift', 'due_date': '2026-10-16'}},
                 {'kind': 'task', 'status': 'pending', 'payload': {'title': 'Wrap the gift', 'due_date': '2026-10-16'}},
                 {'kind': 'task', 'status': 'dismissed', 'payload': {'title': 'Confirm the party address', 'due_date': '2026-10-15'}}]),
]

def resolve(value, ids):
    """Replace '{Name}' placeholders with member IDs throughout drafts or sample outputs."""
    if isinstance(value, str):
        return re.sub(r'\{(\w+)\}', lambda m: ids.get(m.group(1), m.group(0)), value)
    if isinstance(value, list):
        return [resolve(item, ids) for item in value]
    if isinstance(value, dict):
        return {key: resolve(item, ids) for key, item in value.items()}
    return value

def run_checks(case, result, ids):
    """Return (description, passed) for every check of a case."""
    outcomes = []
    for test in case.checks:
        try:
            passed = bool(test(result, ids))
        except (KeyError, TypeError, ValueError):
            passed = False
        outcomes.append((test.description, passed))
    return outcomes
