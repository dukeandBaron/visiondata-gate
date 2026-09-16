import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { finalsReview } from '../web/src/finalsReview.ts';
import { scoringCriteria } from '../web/src/businessTasks.ts';

test('finals uses the five official dimensions and thirteen additive criteria', () => {
  assert.deepEqual(finalsReview.dimensions.map(row => row.points), [20, 25, 25, 15, 15]);
  assert.equal(finalsReview.dimensions.flatMap(row => row.criteria).length, 13);
  assert.equal(finalsReview.dimensions.reduce((n, row) => n + row.points, 0), 100);
  for (const dimension of finalsReview.dimensions) {
    assert.equal(dimension.criteria.reduce((n, row) => n + row.points, 0), dimension.points);
    assert.ok(dimension.href.startsWith('/'));
  }
});

test('review UI separates changed input, frozen replay, and local write runtime', () => {
  const source = readFileSync(new URL('../web/src/pages/PublicReplayPage.tsx', import.meta.url), 'utf8');
  for (const marker of ['CHANGED INPUT', 'FROZEN AGENT CASE', 'LOCAL FULL RUNTIME']) {
    assert.ok(source.includes(marker));
  }
  assert.ok(source.includes('不是项目得分'));
  assert.ok(source.includes('尚缺外部证据'));
});

test('task guidance consumes the same frozen finals dimensions', () => {
  assert.deepEqual(
    scoringCriteria.map(({ id, name, weight }) => ({ id, name, weight })),
    finalsReview.dimensions.map(({ id, title, points }) => ({
      id,
      name: title,
      weight: `${points} 分`,
    })),
  );
});

test('finals dates and presentation window do not inherit semifinal timing', () => {
  assert.equal(finalsReview.deadline, '2026-09-20T12:00:00+08:00');
  assert.equal(finalsReview.presentationMinutes, 8);
  assert.equal(finalsReview.questionsMinutes, 5);
  assert.equal(finalsReview.eventDate, '2026-09-22');
});

test('completion evidence reflects the final source run without erasing external holds', () => {
  const completion = finalsReview.dimensions.find(row => row.id === 'completion');
  assert.equal(completion?.status, 'PASS_LOCAL_HOLD_EXTERNAL');
  assert.match(completion?.boundary ?? '', /f7f31f7 Windows 候选/);
  assert.match(completion?.boundary ?? '', /2070 passed/);
  assert.doesNotMatch(completion?.boundary ?? '', /全仓冻结回归.*HOLD/);
  for (const hold of ['代码签名', '独立干净机', 'Hosted 业务后端', '客户验收']) {
    assert.match(completion?.boundary ?? '', new RegExp(hold));
  }
});
