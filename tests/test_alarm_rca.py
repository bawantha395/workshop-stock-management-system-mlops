"""Alarm root-cause Lambda: guards, evidence rules, redaction and packaging."""
import importlib.util
import io
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'infra/aws/lambda/alarm_rca/alarm_rca.py'


def load():
    spec = importlib.util.spec_from_file_location('alarm_rca', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rca = load()


def conditional_failure():
    return ClientError({'Error': {'Code': 'ConditionalCheckFailedException'}}, 'PutItem')


class Table:
    """In-memory DynamoDB stand-in honouring the two conditions the Lambda uses."""
    def __init__(self):
        self.items = {}

    def put_item(self, TableName, Item, ConditionExpression, ExpressionAttributeValues, ReturnValues):
        key = Item['pk']['S']
        old = self.items.get(key)
        cutoff = int(ExpressionAttributeValues[':cutoff']['N'])
        if old and int(old['reportedAt']['N']) >= cutoff:
            raise conditional_failure()
        self.items[key] = Item
        return {'Attributes': old} if old else {}

    def update_item(self, TableName, Key, UpdateExpression, ExpressionAttributeValues, ReturnValues=None, ConditionExpression=None):
        key = Key['pk']['S']
        item = self.items.setdefault(key, {'pk': Key['pk']})
        if 'flaps' in UpdateExpression:
            item['flaps'] = {'N': str(int(item.get('flaps', {'N': '0'})['N']) + 1)}
            return {'Attributes': {'flaps': item['flaps']}}
        current = int(item.get('reports', {'N': '0'})['N'])
        if current >= int(ExpressionAttributeValues[':cap']['N']):
            raise conditional_failure()
        item['reports'] = {'N': str(current + 1)}
        return {}


class CloudWatch:
    def describe_alarm_history(self, **kwargs):
        return {'AlarmHistoryItems': [{'HistorySummary': 'Alarm updated from OK to ALARM'}]}

    def describe_alarms(self, AlarmNames):
        return {'MetricAlarms': [{'Namespace': 'AWS/SQS', 'MetricName': 'ApproximateNumberOfMessagesVisible',
                                  'Dimensions': [], 'Period': 60, 'Statistic': 'Maximum'}]}

    def get_metric_data(self, **kwargs):
        return {'MetricDataResults': [{'Timestamps': [datetime(2026, 10, 28, 6, 0, tzinfo=timezone.utc)], 'Values': [3.0]}]}


class Logs:
    def __init__(self, rows):
        self.rows, self.queries = rows, []

    def start_query(self, queryString, **kwargs):
        self.queries.append(queryString)
        return {'queryId': str(len(self.queries))}

    def get_query_results(self, queryId):
        rows = self.rows[int(queryId) - 1]
        return {'status': 'Complete', 'results': [[{'field': k, 'value': v} for k, v in row.items()] for row in rows]}

    def stop_query(self, queryId):
        pass


class CloudTrail:
    def __init__(self, events=()):
        self.events = list(events)

    def lookup_events(self, **kwargs):
        assert kwargs['LookupAttributes'] == [{'AttributeKey': 'ReadOnly', 'AttributeValue': 'false'}]
        return {'Events': self.events}


class Sns:
    def __init__(self):
        self.messages = []

    def publish(self, **kwargs):
        self.messages.append(kwargs)


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    for key, value in {'NAME_PREFIX': 'stocklane-dev-', 'TABLE': 't', 'TOPIC_ARN': 'arn:topic',
                       'LOG_GROUP': '/stocklane/stocklane-dev/containers'}.items():
        monkeypatch.setenv(key, value)


def aws(error_rows=None, samples=None, events=()):
    return {'cloudwatch': CloudWatch(), 'dynamodb': Table(), 'sns': Sns(), 'cloudtrail': CloudTrail(events),
            'logs': Logs([error_rows or [], samples or []])}


def alarm_event(name='stocklane-dev-stock-dead-letters', state='ALARM'):
    return {'detail': {'alarmName': name, 'state': {'value': state, 'reason': 'Threshold Crossed'}}}


def test_dead_letter_alarm_names_the_consumer_and_correlates_its_errors():
    clients = aws(error_rows=[{'namespace': 'stocklane-dev', 'container': 'workshop', 'errors': '42'}],
                  samples=[{'container': 'workshop', '@message': 'ERROR failed to apply stock event'}])
    result = rca.handler(alarm_event(), aws=clients)
    assert result['status'] == 'reported'
    assert 'workshop service consumes this queue' in result['likelyCause']
    assert 'top error source' in result['likelyCause']
    body = clients['sns'].messages[0]['Message']
    assert 'redrive' in body and 'Nothing was changed' in body
    assert clients['sns'].messages[0]['Subject'].startswith('[Stocklane RCA]')


def test_cooldown_counts_repeats_instead_of_sending_again():
    clients = aws()
    assert rca.handler(alarm_event(), aws=clients)['status'] == 'reported'
    second = rca.handler(alarm_event(), aws=clients)
    assert second == {'status': 'cooldown', 'alarm': 'stocklane-dev-stock-dead-letters', 'flapsSinceReport': 1}
    assert len(clients['sns'].messages) == 1


def test_daily_cap_stops_reports(monkeypatch):
    monkeypatch.setattr(rca, 'DAILY_CAP', 1)
    clients = aws()
    assert rca.handler(alarm_event('stocklane-dev-a'), aws=clients)['status'] == 'reported'
    assert rca.handler(alarm_event('stocklane-dev-b'), aws=clients)['status'] == 'daily_cap'
    assert len(clients['sns'].messages) == 1


@pytest.mark.parametrize('name,state', [('other-project-alarm', 'ALARM'), ('stocklane-dev-stock-dead-letters', 'OK')])
def test_foreign_or_recovered_alarms_are_ignored(name, state):
    clients = aws()
    assert rca.handler(alarm_event(name, state), aws=clients)['status'] == 'ignored'
    assert clients['sns'].messages == [] and clients['dynamodb'].items == {}


def test_recent_changes_are_reported_and_noisy_events_dropped():
    when = datetime(2026, 10, 28, 5, 50, tzinfo=timezone.utc)
    events = [{'EventName': 'AssumeRole', 'EventTime': when},
              {'EventName': 'UpdateNodegroupConfig', 'EventSource': 'eks.amazonaws.com', 'EventTime': when, 'Username': 'ci'}]
    clients = aws(events=events)
    result = rca.handler(alarm_event('stocklane-dev-application-errors'), aws=clients)
    assert 'UpdateNodegroupConfig' in result['likelyCause']
    assert 'AssumeRole' not in clients['sns'].messages[0]['Message']


def test_secrets_in_log_lines_are_redacted():
    line = rca.redact('ERROR call failed token=abc123 password: hunter2 Authorization="Bearer x"')
    assert 'abc123' not in line and 'hunter2' not in line and '[REDACTED]' in line


def test_committed_package_matches_source():
    sys.path.insert(0, str(ROOT / 'scripts'))
    from build_alarm_rca import package
    def contents(data):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return {name: archive.read(name) for name in archive.namelist()}
    committed = (ROOT / 'infra/aws/lambda/alarm-rca.zip').read_bytes()
    assert contents(committed) == contents(package()), 'Run python scripts/build_alarm_rca.py and commit the zip'
