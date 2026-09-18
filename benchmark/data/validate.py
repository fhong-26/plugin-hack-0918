"""Validate this static dataset without calling a model or executing any case."""
import hashlib
import json
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
def read(name):
    return json.loads((BASE / name).read_text())
def lines(name):
    return [json.loads(line) for line in (BASE / name).read_text().splitlines()]

tasks, answers = lines('tasks.jsonl'), lines('answers.jsonl')
families, snapshot, policy, manifest = [read(name) for name in
    ['families.json', 'runtime-tools.json', 'host-policy.json', 'manifest.json']]
catalog = {tool['name']: tool['description'] for tool in snapshot['tools']}
assert len(catalog) == len(snapshot['tools'])
assert set(catalog) <= set(snapshot['all_exposed_names'])
assert set(catalog) == set().union(*map(set, families.values()))
assert len(tasks) == len(answers) == 50
assert len({t['id'] for t in tasks}) == 50
assert len({a['id'] for a in answers}) == 50
assert {t['id'] for t in tasks} == {a['id'] for a in answers}
assert Counter(t['family'] for t in tasks) == {f: 10 for f in families}
by_id = {a['id']: a for a in answers}
for task in tasks:
    assert set(task) == {'id', 'family', 'scenario_group', 'input'}
    inp = task['input']
    assert set(inp) == {'instruction', 'context', 'host_instructions', 'tools'}
    assert isinstance(inp['instruction'], str) and inp['instruction'].strip()
    assert isinstance(inp['context'], list) and inp['context']
    assert all(isinstance(s, str) and s.strip() for s in inp['context'])
    assert inp['host_instructions'] == policy['instructions']
    names = [t['id'] for t in inp['tools']]
    assert len(names) == len(set(names))
    assert set(names) == set(families[task['family']])
    assert 'exec_command' in names
    assert not {'ABSTAIN', 'ASK_USER', 'ANSWER'} & set(names)
    for tool in inp['tools']:
        assert set(tool) == {'id', 'description'}
        assert tool['description'] == catalog[tool['id']]
    answer = by_id[task['id']]
    assert answer['tool_id'] in names
    assert answer['rationale'].strip()
    assert answer['nearest_alternatives']
    assert set(answer['nearest_alternatives']) <= set(names) - {answer['tool_id']}
    # No exact gold tool name appears in the human-authored request or context.
    assert answer['tool_id'] not in inp['instruction']
    assert all(answer['tool_id'] not in s for s in inp['context'])
for name, expected in manifest['sha256'].items():
    assert hashlib.sha256((BASE / name).read_bytes()).hexdigest() == expected, name
goal_hash = (BASE / 'GOAL.sha256').read_text().split()[0]
assert hashlib.sha256((BASE / 'GOAL.md').read_bytes()).hexdigest() == goal_hash
labels = Counter(a['tool_id'] for a in answers)
print(json.dumps({'status': 'PASS', 'cases': 50, 'real_tools': len(catalog),
                  'distinct_correct_tools': len(labels),
                  'global_majority_label_count': labels.most_common(1)[0][1],
                  'family_candidate_counts': {f: len(v) for f, v in families.items()}}, indent=2))
