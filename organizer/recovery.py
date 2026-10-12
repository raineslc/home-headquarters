from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import SetupRecord

def snapshot(household):
    return {'format': 'home-headquarters', 'version': 1, 'scope': 'foundation',
            'exported_at': timezone.now().isoformat(),
            'household': {'name': household.name, 'timezone': household.timezone},
            'records': list(SetupRecord.objects.filter(household=household)
                            .order_by('created_at').values('title'))}

def validate_snapshot(data):
    if not isinstance(data, dict) or set(data) != {'format', 'version', 'scope', 'exported_at', 'household', 'records'}:
        raise ValidationError('This is not a supported household export.')
    if data['format'] != 'home-headquarters' or type(data['version']) is not int or data['version'] != 1 or data['scope'] != 'foundation':
        raise ValidationError('This export version is not supported.')
    if not isinstance(data['household'], dict) or set(data['household']) != {'name', 'timezone'}:
        raise ValidationError('Household information is invalid.')
    name = data['household']['name']
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ValidationError('Household name is invalid.')
    try:
        ZoneInfo(data['household']['timezone'])
        stamp = datetime.fromisoformat(data['exported_at'])
        if stamp.tzinfo is None:
            raise ValueError('Missing time zone')
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        raise ValidationError('Export date or time zone is invalid.')
    if not isinstance(data['records'], list) or len(data['records']) > 1000:
        raise ValidationError('An export can contain at most 1,000 foundation records.')
    for row in data['records']:
        if not isinstance(row, dict) or set(row) != {'title'} or not isinstance(row['title'], str) or not 1 <= len(row['title'].strip()) <= 200:
            raise ValidationError('A record has an invalid title.')
    return data['records']
