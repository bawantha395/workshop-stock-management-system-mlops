"""Rule-based root-cause report for Stocklane CloudWatch alarms.

EventBridge invokes this function when a project alarm enters ALARM. It applies
DynamoDB guards (per-alarm cooldown, daily cap), gathers read-only evidence
(alarm history and metric, container error logs, recent CloudTrail changes),
applies simple rules and emails a report through the operations SNS topic.
It never changes infrastructure. Conclusions are heuristics for a human to check.
"""
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

LOOKBACK_MINUTES = int(os.environ.get('LOOKBACK_MINUTES', '30'))
COOLDOWN_HOURS = int(os.environ.get('COOLDOWN_HOURS', '6'))
DAILY_CAP = int(os.environ.get('DAILY_CAP', '10'))
QUERY_TIMEOUT_SECONDS = int(os.environ.get('QUERY_TIMEOUT_SECONDS', '40'))
NOISY_EVENTS = {'AssumeRole', 'AssumeRoleWithWebIdentity', 'GenerateDataKey', 'Decrypt', 'Encrypt',
                'CreateLogStream', 'PutLogEvents', 'StartQuery', 'StopQuery', 'ConsoleLogin',
                'PutMetricData', 'SendMessage', 'DeleteMessage', 'ReceiveMessage', 'ChangeMessageVisibility'}
# Queue name suffix -> service that consumes it (see Terraform data.tf).
QUEUE_CONSUMERS = {'stock': 'workshop', 'catalogue': 'vision'}
SECRET_PATTERN = re.compile(r'(?i)(token|password|secret|authorization|api[_-]?key)(["\s:=]+)([^\s",&]+)')

ERROR_COUNT_QUERY = ('fields kubernetes.namespace_name as namespace, kubernetes.container_name as container '
                     '| filter @message like /(?i)(error|exception|fatal|refused|timed out|timeout)/ '
                     '| stats count(*) as errors by namespace, container | sort errors desc | limit 10')
ERROR_SAMPLE_QUERY = ('fields @timestamp, kubernetes.container_name as container, @message '
                      '| filter @message like /(?i)(error|exception|fatal|refused|timed out|timeout)/ '
                      '| sort @timestamp desc | limit 5')


def clients():
    return {name: boto3.client(name) for name in ('cloudwatch', 'logs', 'cloudtrail', 'dynamodb', 'sns')}


def handler(event, context=None, aws=None):
    aws = aws or clients()
    detail = event.get('detail', {})
    alarm = detail.get('alarmName', '')
    state = detail.get('state', {}).get('value')
    if state != 'ALARM' or not alarm.startswith(os.environ['NAME_PREFIX']):
        return {'status': 'ignored', 'alarm': alarm}
    now = int(time.time())
    allowed, flaps = claim_alarm(aws['dynamodb'], alarm, now)
    if not allowed:
        return {'status': 'cooldown', 'alarm': alarm, 'flapsSinceReport': flaps}
    if not claim_daily_slot(aws['dynamodb'], now):
        return {'status': 'daily_cap', 'alarm': alarm}
    started = datetime.fromtimestamp(now, timezone.utc)
    evidence = collect(aws, alarm, detail, started)
    report = analyse(alarm, detail, evidence, flaps)
    subject = ('[Stocklane RCA] ' + alarm)[:100]
    aws['sns'].publish(TopicArn=os.environ['TOPIC_ARN'], Subject=subject, Message=render(alarm, detail, report, evidence))
    return {'status': 'reported', 'alarm': alarm, 'likelyCause': report['cause']}


def claim_alarm(db, alarm, now):
    """Atomically allow one report per alarm per cooldown; count later flaps."""
    table = os.environ['TABLE']
    try:
        old = db.put_item(TableName=table, Item={'pk': {'S': 'alarm#' + alarm}, 'reportedAt': {'N': str(now)},
                                                  'flaps': {'N': '0'}, 'expires': {'N': str(now + 7 * 86400)}},
                          ConditionExpression='attribute_not_exists(pk) OR reportedAt < :cutoff',
                          ExpressionAttributeValues={':cutoff': {'N': str(now - COOLDOWN_HOURS * 3600)}},
                          ReturnValues='ALL_OLD')
        return True, int(old.get('Attributes', {}).get('flaps', {}).get('N', '0'))
    except ClientError as error:
        if error.response['Error']['Code'] != 'ConditionalCheckFailedException':
            raise
    updated = db.update_item(TableName=table, Key={'pk': {'S': 'alarm#' + alarm}},
                             UpdateExpression='ADD flaps :one', ExpressionAttributeValues={':one': {'N': '1'}},
                             ReturnValues='UPDATED_NEW')
    return False, int(updated['Attributes']['flaps']['N'])


def claim_daily_slot(db, now):
    day = datetime.fromtimestamp(now, timezone.utc).strftime('%Y-%m-%d')
    try:
        db.update_item(TableName=os.environ['TABLE'], Key={'pk': {'S': 'day#' + day}},
                       UpdateExpression='ADD reports :one SET expires = :expires',
                       ConditionExpression='attribute_not_exists(reports) OR reports < :cap',
                       ExpressionAttributeValues={':one': {'N': '1'}, ':cap': {'N': str(DAILY_CAP)},
                                                  ':expires': {'N': str(now + 3 * 86400)}})
        return True
    except ClientError as error:
        if error.response['Error']['Code'] == 'ConditionalCheckFailedException':
            return False
        raise


def collect(aws, alarm, detail, now):
    start = now - timedelta(minutes=LOOKBACK_MINUTES)
    evidence = {'window': (start, now), 'errors': [], 'samples': [], 'changes': [], 'history': 0, 'metric': [], 'notes': []}
    try:
        history = aws['cloudwatch'].describe_alarm_history(AlarmName=alarm, HistoryItemType='StateUpdate',
                                                           StartDate=now - timedelta(hours=24), EndDate=now, MaxRecords=100)
        evidence['history'] = sum(1 for item in history.get('AlarmHistoryItems', [])
                                  if 'to ALARM' in item.get('HistorySummary', ''))
    except ClientError as error:
        evidence['notes'].append('Alarm history unavailable: ' + error.response['Error']['Code'])
    evidence['metric'] = metric_points(aws['cloudwatch'], alarm, start, now, evidence['notes'])
    log_group = os.environ['LOG_GROUP']
    evidence['errors'] = run_query(aws['logs'], log_group, ERROR_COUNT_QUERY, start, now, evidence['notes'])
    evidence['samples'] = run_query(aws['logs'], log_group, ERROR_SAMPLE_QUERY, start, now, evidence['notes'])
    evidence['changes'] = recent_changes(aws['cloudtrail'], now - timedelta(minutes=LOOKBACK_MINUTES * 2), now, evidence['notes'])
    return evidence


def metric_points(cloudwatch, alarm, start, end, notes):
    try:
        alarms = cloudwatch.describe_alarms(AlarmNames=[alarm]).get('MetricAlarms', [])
    except ClientError as error:
        notes.append('Alarm definition unavailable: ' + error.response['Error']['Code'])
        return []
    if not alarms or not alarms[0].get('MetricName'):
        return []
    a = alarms[0]
    query = {'Id': 'm1', 'MetricStat': {'Metric': {'Namespace': a['Namespace'], 'MetricName': a['MetricName'],
                                                    'Dimensions': a.get('Dimensions', [])},
                                         'Period': a.get('Period', 60), 'Stat': a.get('Statistic', 'Maximum')}}
    result = cloudwatch.get_metric_data(MetricDataQueries=[query], StartTime=start, EndTime=end, ScanBy='TimestampAscending')
    series = result.get('MetricDataResults', [{}])[0]
    return list(zip(series.get('Timestamps', []), series.get('Values', [])))


def run_query(logs, log_group, query, start, end, notes):
    try:
        query_id = logs.start_query(logGroupName=log_group, startTime=int(start.timestamp()), endTime=int(end.timestamp()),
                                    queryString=query, limit=10)['queryId']
    except ClientError as error:
        notes.append('Logs Insights unavailable: ' + error.response['Error']['Code'])
        return []
    deadline = time.time() + QUERY_TIMEOUT_SECONDS
    while time.time() < deadline:
        result = logs.get_query_results(queryId=query_id)
        if result['status'] in ('Complete', 'Failed', 'Cancelled', 'Timeout'):
            if result['status'] != 'Complete':
                notes.append('Logs Insights query ' + result['status'].lower())
            return [{f['field']: f['value'] for f in row if not f['field'].startswith('@ptr')} for row in result.get('results', [])]
        time.sleep(1)
    logs.stop_query(queryId=query_id)
    notes.append('Logs Insights query timed out')
    return []


def recent_changes(cloudtrail, start, end, notes):
    try:
        events = cloudtrail.lookup_events(LookupAttributes=[{'AttributeKey': 'ReadOnly', 'AttributeValue': 'false'}],
                                          StartTime=start, EndTime=end, MaxResults=50).get('Events', [])
    except ClientError as error:
        notes.append('CloudTrail unavailable: ' + error.response['Error']['Code'])
        return []
    changes = [{'time': e['EventTime'], 'name': e['EventName'], 'source': e.get('EventSource', ''),
                'user': e.get('Username', '')} for e in events if e['EventName'] not in NOISY_EVENTS]
    return changes[:10]


def analyse(alarm, detail, evidence, flaps):
    queue = re.search(r'-(stock|catalogue)-(backlog-age|dead-letters)$', alarm)
    top = evidence['errors'][0] if evidence['errors'] else None
    top_text = f"{top.get('container', '?')} in {top.get('namespace', '?')} ({top.get('errors', '?')} error lines)" if top else None
    actions = []
    if queue:
        consumer = QUEUE_CONSUMERS[queue.group(1)]
        kind = 'messages failed processing 5 times and moved to the dead-letter queue' if queue.group(2) == 'dead-letters' \
            else 'messages are waiting longer than expected, so the consumer is slow or not running'
        cause = f'{queue.group(1)} queue {kind}. The {consumer} service consumes this queue.'
        if top and top.get('container') == consumer:
            cause += f' It is also the top error source in the window: {top_text}.'
        actions += [f'Check {consumer} pods: kubectl -n stocklane-dev get pods -l app={consumer}',
                    f'Read recent {consumer} logs for the failing message type',
                    'After fixing, redrive the DLQ messages from the SQS console (do not delete them)']
    elif top:
        cause = f'Most errors in the window came from {top_text}.'
        actions += [f"Check {top.get('container')} pod status and restarts", 'Read the sample error lines below']
    else:
        cause = 'No error logs or queue pattern matched. The alarm may reflect load or an external dependency.'
        actions += ['Open the alarm metric in CloudWatch and compare with normal traffic']
    if evidence['changes']:
        first = evidence['changes'][-1]
        cause += f" {len(evidence['changes'])} AWS change(s) happened shortly before, starting with {first['name']} ({first['source']})."
        actions.append('Review the recent changes listed below; roll back if one matches the start of the alarm')
    if evidence['history'] > 2 or flaps:
        actions.append(f"The alarm fired {evidence['history']} times in 24 h ({flaps} suppressed repeats); consider tuning its threshold or fixing the flapping cause")
    return {'cause': cause, 'actions': actions[:5]}


def redact(text):
    return SECRET_PATTERN.sub(lambda m: m.group(1) + m.group(2) + '[REDACTED]', str(text))[:400]


def render(alarm, detail, report, evidence):
    start, end = evidence['window']
    lines = [f'Alarm: {alarm}', f"Reason: {detail.get('state', {}).get('reason', 'n/a')}",
             f"Window: {start:%Y-%m-%d %H:%M} to {end:%H:%M} UTC", '', 'LIKELY CAUSE (rule-based, verify before acting)',
             report['cause'], '', 'RECOMMENDED ACTIONS'] + [f'{i}. {a}' for i, a in enumerate(report['actions'], 1)]
    if evidence['metric']:
        lines += ['', 'ALARM METRIC (latest values)'] + [f'{t:%H:%M} {v:g}' for t, v in evidence['metric'][-6:]]
    lines += ['', 'TOP ERROR SOURCES'] + ([f"{e.get('namespace', '?')}/{e.get('container', '?')}: {e.get('errors', '?')}" for e in evidence['errors']] or ['none found'])
    if evidence['samples']:
        lines += ['', 'SAMPLE ERROR LINES'] + [f"[{s.get('container', '?')}] {redact(s.get('@message', ''))}" for s in evidence['samples']]
    lines += ['', 'RECENT AWS CHANGES'] + ([f"{c['time']:%H:%M} {c['name']} ({c['source']}) by {c['user'] or 'unknown'}" for c in evidence['changes']] or ['none found'])
    if evidence['notes']:
        lines += ['', 'NOTES'] + evidence['notes']
    lines += ['', 'This report is read-only analysis. Nothing was changed in the account.']
    return '\n'.join(lines)
