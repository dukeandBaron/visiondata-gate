import test from 'node:test';
import assert from 'node:assert/strict';
import { businessTasks, findBusinessTask, businessTaskUrl, scoringCriteria } from '../web/src/businessTasks.ts';

test('three customer tasks have different outcomes and explicit proof requirements', () => {
  assert.equal(businessTasks.length, 3);
  assert.equal(new Set(businessTasks.map(task => task.id)).size, 3);
  for (const task of businessTasks) {
    assert.ok(task.buyer && task.user && task.trigger && task.outcome);
    assert.ok(task.inputs.length && task.limitations.length && task.steps.length);
    for (const key of scoringCriteria.map(c => c.id)) assert.ok(task.proof[key]);
    assert.equal('completed' in task, false);
    assert.equal('production_release_allowed' in task, false);
  }
});

test('task-purpose links cannot create, approve, or change authority', () => {
  for (const task of businessTasks) {
    for (const route of ['/start', '/pilot', '/workspace']) {
      const url = new URL(businessTaskUrl(task.id, route), 'http://local.test');
      assert.equal(url.searchParams.get('purpose'), task.id);
      assert.deepEqual([...url.searchParams.keys()], ['purpose']);
      assert.doesNotMatch(url.href, /visiondata|dukeandbaron|approve|execute|create=/i);
    }
  }
  assert.throws(() => businessTaskUrl('unknown', '/pilot'));
  assert.equal(findBusinessTask('unknown'), undefined);
});

test('annotation task preserves semantic review and does not promise automatic labeling', () => {
  const task = findBusinessTask('annotation-rework');
  assert.ok(task);
  assert.ok(task.limitations.some(text => text.includes('语义') && text.includes('人工')));
  assert.ok(task.limitations.some(text => text.includes('多人')));
  assert.ok(task.steps.some(step => step.href.includes('capa')));
});

test('dataset reuse requires a second observed task and a fixed version', () => {
  const task = findBusinessTask('dataset-reuse');
  assert.ok(task);
  assert.ok(task.inputs.some(text => text.includes('版本')));
  assert.match(task.proof.value, /第二|新批次/);
  assert.ok(task.limitations.some(text => text.includes('持续监控')));
  assert.ok(task.limitations.some(text => text.includes('累计快照')));
  assert.ok(task.limitations.some(text => text.includes('合同内容与摘要')));
});
