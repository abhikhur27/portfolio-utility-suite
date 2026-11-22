"""Bitemporal facts, small exact assignments and reproducible decision changes."""
from __future__ import annotations

import copy
import json
import re
import sqlite3
from pathlib import Path

MAX_EVENTS = 10_000
MAX_RESOURCES = 10
MAX_JOBS = 32
MAX_CHANGES = 12


def integer(value, name, minimum=0, maximum=10**15):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer in [{minimum}, {maximum}]')
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', value):
        raise ValueError('Identifiers must contain 1-80 letters, digits, dots, underscores or hyphens')
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def validate(event):
    required = {'event_id', 'kind', 'entity', 'valid_at', 'known_at', 'payload'}
    if not isinstance(event, dict) or set(event) != required:
        raise ValueError('Each event requires exactly event_id, kind, entity, valid_at, known_at, payload')
    identifier(event['event_id']); identifier(event['entity'])
    if event['kind'] not in ('job', 'resource'):
        raise ValueError('kind must be job or resource')
    integer(event['valid_at'], 'valid_at'); integer(event['known_at'], 'known_at')
    payload = event['payload']
    if payload is None:
        return copy.deepcopy(event)
    if not isinstance(payload, dict):
        raise ValueError('payload must be an object or null (a tombstone)')
    fields = {'priority', 'skill', 'deadline'} if event['kind'] == 'job' else {'skills', 'available', 'costs'}
    if not fields <= set(payload) or set(payload) - fields - {'label'}:
        raise ValueError(f'{event["kind"]} payload requires {sorted(fields)} and optional label')
    if 'label' in payload and (not isinstance(payload['label'], str) or len(payload['label']) > 200):
        raise ValueError('label must be a string of at most 200 characters')
    if event['kind'] == 'job':
        integer(payload['priority'], 'priority', 1, 1_000_000)
        integer(payload['deadline'], 'deadline', 0, 1_000_000)
        identifier(payload['skill'])
    else:
        skills = payload['skills']
        if not isinstance(skills, list) or len(skills) > 32 or any(not isinstance(s, str) for s in skills):
            raise ValueError('skills must be a list of at most 32 identifiers')
        for skill in skills:
            identifier(skill)
        if len(set(skills)) != len(skills) or type(payload['available']) is not bool:
            raise ValueError('skills must be unique and available must be boolean')
        if not isinstance(payload['costs'], dict) or len(payload['costs']) > 64:
            raise ValueError('costs must map at most 64 job identifiers to nonnegative integers')
        for key, value in payload['costs'].items():
            identifier(key); integer(value, 'cost', 0, 1_000_000)
    canonical(event)
    return copy.deepcopy(event)


def validated_events(events):
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValueError(f'events must be a list of at most {MAX_EVENTS} records')
    unique = {}
    for item in events:
        event = validate(item)
        previous = unique.get(event['event_id'])
        if previous is not None and canonical(previous) != canonical(event):
            raise ValueError(f'Conflicting event_id: {event["event_id"]}')
        unique[event['event_id']] = event
    return list(unique.values())


def snapshot(events, valid_at, known_at):
    """Latest effective state available by a knowledge cutoff, including tombstones.

    Full-state records are ordered by valid_at, then known_at, then event_id.
    Input/arrival order cannot silently choose a winner.
    """
    integer(valid_at, 'valid_at'); integer(known_at, 'known_at')
    projection = {}
    for event in validated_events(events):
        if event['valid_at'] > valid_at or event['known_at'] > known_at:
            continue
        key = event['kind'] + '/' + event['entity']
        previous = projection.get(key)
        rank = lambda item: (item['valid_at'], item['known_at'], item['event_id'])
        if previous is None or rank(event) > rank(previous):
            projection[key] = event
    return dict(sorted(projection.items()))


def allocate(state):
    """Exact bounded matching: priority first, cost second, lexical pairs third."""
    resources, jobs = {}, {}
    if not isinstance(state, dict):
        raise ValueError('state must be a snapshot object')
    for key, record in state.items():
        event = validate(record)
        if key != event['kind'] + '/' + event['entity']:
            raise ValueError('Snapshot key does not match its record')
        if event['payload'] is not None:
            (jobs if event['kind'] == 'job' else resources)[event['entity']] = event['payload']
    if len(resources) > MAX_RESOURCES or len(jobs) > MAX_JOBS:
        raise ValueError(f'Exact allocation supports at most {MAX_RESOURCES} resources and {MAX_JOBS} jobs')
    resource_ids = sorted(resources)
    # For a fixed used-resource mask, future choices are identical. Keep its best prefix.
    states = {0: (0, 0, ())}
    rank = lambda result: (-result[0], result[1], result[2])
    for job_id, task in sorted(jobs.items()):
        following = dict(states)  # Leaving a job unassigned is always possible.
        for mask, (priority, cost, pairs) in states.items():
            for index, resource_id in enumerate(resource_ids):
                resource = resources[resource_id]
                eta = resource['costs'].get(job_id)
                if mask & (1 << index) or not resource['available']:
                    continue
                if task['skill'] not in resource['skills'] or eta is None or eta > task['deadline']:
                    continue
                target = mask | (1 << index)
                candidate = (priority + task['priority'], cost + eta, pairs + ((job_id, resource_id),))
                if target not in following or rank(candidate) < rank(following[target]):
                    following[target] = candidate
        states = following
    priority, cost, pairs = min(states.values(), key=rank)
    return {'assignments': dict(pairs), 'unassigned': sorted(set(jobs) - dict(pairs).keys()),
            'covered_priority': priority, 'travel_cost': cost}


def append_events(path, events):
    """Atomically append a batch. Identical IDs are no-ops; changed IDs roll back."""
    records = validated_events(events)
    connection = sqlite3.connect(str(path), isolation_level=None)
    try:
        connection.execute('CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        connection.execute('BEGIN IMMEDIATE')
        inserted = 0
        for event in records:
            encoded = canonical(event)
            previous = connection.execute('SELECT body FROM events WHERE event_id=?', (event['event_id'],)).fetchone()
            if previous:
                if previous[0] != encoded:
                    raise ValueError(f'Conflicting event_id: {event["event_id"]}')
                continue
            connection.execute('INSERT INTO events VALUES (?,?)', (event['event_id'], encoded))
            inserted += 1
        if connection.execute('SELECT COUNT(*) FROM events').fetchone()[0] > MAX_EVENTS:
            raise ValueError(f'Journal exceeds {MAX_EVENTS} events')
        connection.commit()
        return inserted
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def read_events(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        rows = connection.execute('SELECT body FROM events ORDER BY event_id LIMIT ?', (MAX_EVENTS + 1,)).fetchall()
        return validated_events([json.loads(row[0]) for row in rows])
    finally:
        connection.close()


def explain(events, valid_at, before, after):
    """Reproduce the new decision with a deletion-1-minimal subset of fact changes.

    This is an explanation inside the specified model, not real-world causality
    or a globally minimum-cardinality explanation.
    """
    integer(before, 'before'); integer(after, 'after')
    if before > after:
        raise ValueError('before must not exceed after')
    old = snapshot(events, valid_at, before)
    new = snapshot(events, valid_at, after)
    original, target = allocate(old), allocate(new)
    changes = [key for key in sorted(old.keys() | new.keys())
               if (old.get(key) or {}).get('payload') != (new.get(key) or {}).get('payload')]
    if len(changes) > MAX_CHANGES:
        raise ValueError(f'Explanation supports at most {MAX_CHANGES} changed facts')
    solves = 2

    def replay(keys):
        nonlocal solves
        solves += 1
        hypothetical = copy.deepcopy(old)
        for key in keys:
            if key in new:
                hypothetical[key] = new[key]
            else:
                hypothetical.pop(key, None)
        return allocate(hypothetical)

    selected = list(changes) if original != target else []
    while True:
        removed = False
        for key in list(selected):
            candidate = [item for item in selected if item != key]
            if replay(candidate) == target:
                selected = candidate
                removed = True
        if not removed:
            break
    assert replay(selected) == target
    # The last fixed-point pass established deletion-1-minimality, not global minimality.
    return {'schema_version': 1, 'valid_at': valid_at, 'known_before': before, 'known_after': after,
            'before': original, 'after': target, 'changed_facts': changes,
            'witness': [{'key': key, 'before': old.get(key), 'after': new.get(key)} for key in selected],
            'deletion_1_minimal': True, 'solver_calls': solves,
            'semantics': 'Full-state events; effective time, then knowledge time, then event ID. Exact bounded assignment; model-relative explanation.'}
