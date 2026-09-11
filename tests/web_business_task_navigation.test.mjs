import test from 'node:test';
import assert from 'node:assert/strict';
import { workbookAssetSearch, snapshotTaskUrl } from '../web/src/businessTaskNavigation.ts';

test('asset selection and upload retain purpose but remove stale one-shot parameters', () => {
  const original = new URLSearchParams('asset=old&purpose=annotation-rework&tour=1&import=1');
  const result = workbookAssetSearch(original, 'asset-new');
  assert.deepEqual([...result], [['purpose', 'annotation-rework'], ['asset', 'asset-new']]);
  assert.equal(original.get('asset'), 'old');
});

test('empty assets retain the chosen purpose without keeping stale identities', () => {
  assert.equal(workbookAssetSearch(new URLSearchParams('purpose=dataset-reuse&asset=old')).toString(), 'purpose=dataset-reuse');
  assert.equal(workbookAssetSearch(new URLSearchParams()).toString(), '');
});

test('unknown purposes remain explicit for the recoverable UI', () => {
  assert.equal(workbookAssetSearch(new URLSearchParams('purpose=unknown'), 'new').get('purpose'), 'unknown');
});

test('snapshot handoff keeps the real source identity and purpose separate', () => {
  const route = new URL(snapshotTaskUrl('source&task=forged', 'annotation-rework'), 'https://local.test');
  assert.equal(route.searchParams.get('source'), 'source&task=forged');
  assert.equal(route.searchParams.get('purpose'), 'annotation-rework');
  assert.equal(route.searchParams.get('create'), '1');
  assert.equal(route.searchParams.has('task'), false);
  assert.equal(route.searchParams.has('intended_use'), false);
  assert.equal(route.searchParams.has('approve'), false);
  assert.equal(new URL(snapshotTaskUrl('source', null), 'https://local.test').searchParams.has('purpose'), false);
});
