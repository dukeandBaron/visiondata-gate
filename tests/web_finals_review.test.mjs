import test from 'node:test';
import assert from 'node:assert/strict';
import { finalsReview } from '../web/src/finalsReview.ts';

test('finals uses the five official dimensions and thirteen additive criteria', () => {
  assert.deepEqual(finalsReview.dimensions.map(row => row.points), [20, 25, 25, 15, 15]);
  assert.equal(finalsReview.dimensions.flatMap(row => row.criteria).length, 13);
  assert.equal(finalsReview.dimensions.reduce((n, row) => n + row.points, 0), 100);
  for (const dimension of finalsReview.dimensions) {
    assert.equal(dimension.criteria.reduce((n, row) => n + row.points, 0), dimension.points);
    assert.ok(dimension.href.startsWith('/'));
  }
});

test('finals dates and presentation window do not inherit semifinal timing', () => {
  assert.equal(finalsReview.deadline, '2026-09-20T12:00:00+08:00');
  assert.equal(finalsReview.presentationMinutes, 8);
  assert.equal(finalsReview.questionsMinutes, 5);
  assert.equal(finalsReview.eventDate, '2026-09-22');
});
