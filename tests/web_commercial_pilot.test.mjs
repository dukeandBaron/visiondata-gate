import test from 'node:test';
import assert from 'node:assert/strict';
import { buildPilotPlan, parsePilotPlan, emptyPilotDraft, pilotFields } from '../web/src/commercialPilot.ts';

function validDraft() {
  const draft = emptyPilotDraft();
  for (const field of pilotFields) draft[field.key] = `测试 ${field.label}`;
  return draft;
}

test('exported plans never carry authority or fabricated outcomes', () => {
  const plan = buildPilotPlan({ ...validDraft(), production_release_allowed: true, status: 'APPROVED', measured_roi: 1 });
  assert.equal(plan.status, 'DRAFT_NOT_APPROVED');
  assert.equal(plan.customer_validation, 'NOT_MEASURED');
  assert.equal(plan.production_release_allowed, false);
  assert.equal(plan.machine_write_permitted, false);
  assert.equal('measured_roi' in plan, false);
  for (const metric of plan.measurements) {
    assert.equal(metric.baseline, null);
    assert.equal(metric.after, null);
    assert.equal(metric.evidence_ref, null);
    assert.equal(metric.status, 'NOT_MEASURED');
  }
});

test('blank scope and empty, duplicated or unrecognized metrics fail validation', () => {
  assert.throws(() => buildPilotPlan(emptyPilotDraft()), /项目代号/);
  for (const metricIds of [[], ['unknown'], ['evidence_time', 'evidence_time']]) {
    assert.throws(() => buildPilotPlan({ ...validDraft(), metricIds }), /指标/);
  }
  assert.throws(() => buildPilotPlan({ ...validDraft(), problem: ' '.repeat(30) }), /实际问题/);
});

test('draft export/import roundtrip preserves the actual user scope and selected metrics', () => {
  const draft = { ...validDraft(), problem: '<img src=x onerror=alert(1)>\n测试换型', metricIds: ['miss_rate', 'inspection_ng', 'physical_defect'] };
  assert.deepEqual(parsePilotPlan(JSON.stringify(buildPilotPlan(draft))), draft);
});

test('import refuses fabricated approval, measurement and missing authority flags', () => {
  for (const change of [{ status: 'APPROVED' }, { production_release_allowed: true }, { machine_write_permitted: undefined }, { customer_validation: 'VERIFIED' }]) {
    assert.throws(() => parsePilotPlan(JSON.stringify({ ...buildPilotPlan(validDraft()), ...change })), /草稿/);
  }
  const plan = buildPilotPlan(validDraft());
  plan.measurements[0].after = 0;
  assert.throws(() => parsePilotPlan(JSON.stringify(plan)), /测量结论/);
});

test('NG alarms, missed defects and physical defects remain distinct denominators', () => {
  const plan = buildPilotPlan({ ...validDraft(), metricIds: ['inspection_ng', 'miss_rate', 'false_reject', 'physical_defect'] });
  assert.equal(new Set(plan.measurements.map((m) => m.unit)).size, 4);
  assert.match(plan.measurements.find((m) => m.id === 'inspection_ng').definition, /漏检增加/);
  assert.match(plan.measurements.find((m) => m.id === 'physical_defect').definition, /不能推断/);
});

test('import rejects oversized, malformed and mismatched measurement plans', () => {
  assert.throws(() => parsePilotPlan('x'.repeat(50001)), /50 KB/);
  assert.throws(() => parsePilotPlan('{'));
  const plan = buildPilotPlan(validDraft());
  plan.measurements.pop();
  assert.throws(() => parsePilotPlan(JSON.stringify(plan)), /测量结论/);
});

test('v2 plan freezes the selected customer task without runtime approval', () => {
  const draft = { ...validDraft(), businessTaskId: 'annotation-rework' };
  const plan = buildPilotPlan(draft);
  assert.equal(plan.schema_version, 'industrial-delivery.pilot-plan.v2');
  assert.equal(plan.scope.businessTaskId, 'annotation-rework');
  assert.match(plan.business_task.title, /人工复核/);
  assert.deepEqual(parsePilotPlan(JSON.stringify(plan)), draft);
  assert.equal(plan.status, 'DRAFT_NOT_APPROVED');
});

test('legacy v1 plans map explicitly to data acceptance while unknown IDs fail', () => {
  const plan = buildPilotPlan(validDraft());
  plan.schema_version = 'industrial-delivery.pilot-plan.v1';
  delete plan.scope.businessTaskId;
  delete plan.business_task;
  assert.equal(parsePilotPlan(JSON.stringify(plan)).businessTaskId, 'dataset-acceptance');
  assert.throws(() => buildPilotPlan({ ...validDraft(), businessTaskId:'unknown-task' }), /业务任务/);
});

test('task-completion measurement is separate from Gate PASS and remediation', () => {
  const plan = buildPilotPlan({ ...validDraft(), metricIds:['independent_completion', 'annotation_rework_acceptance'] });
  assert.equal(plan.measurements.length, 2);
  assert.match(plan.measurements[0].definition, /阻断/);
  assert.match(plan.measurements[1].evidence, /独立/);
  assert.equal(plan.measurements[1].after, null);
});

test('v2 import refuses missing or mismatched task bindings', () => {
  const plan = buildPilotPlan(validDraft());
  plan.business_task.id = 'annotation-rework';
  assert.throws(() => parsePilotPlan(JSON.stringify(plan)), /业务任务/);
  delete plan.business_task;
  assert.throws(() => parsePilotPlan(JSON.stringify(plan)), /业务任务/);
});
