// Run with playwright-cli --session scoring-business run-code --filename this-file.
// Preview port 4193 must serve the isolated public build. All inputs are synthetic.
async (page) => {
  const passed = [], failures = [], errors = [], writes = [];
  function check(condition, name) { (condition ? passed : failures).push(name); }
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => { if (!['GET', 'HEAD'].includes(request.method())) writes.push(request.method() + ' ' + request.url()); });
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto('http://127.0.0.1:4193/');
  await page.getByRole('heading', { name: /让每批数据/ }).waitFor();
  await page.screenshot({ path: 'output/playwright/scoring-business-home.png' });
  await page.getByRole('link', { name: '应用场景', exact: true }).click();
  check(!page.url().includes('#business-story'), 'homepage anchor retains router');
  await page.getByRole('button', { name: /可操作子任务 人工复核/ }).click();
  await page.getByRole('button', { name: /3 返修并留下版本/ }).click();
  check((await page.locator('.commercial-story__detail').innerText()).includes('追加版本'), 'story displays selected task and step');
  await page.getByRole('link', { name: '查看本任务指引', exact: true }).click();
  await page.getByRole('heading', { name: '这批数据，下一步需要做什么？' }).waitFor();
  check(page.url().includes('purpose=annotation-rework'), 'story carries selected purpose to guide');
  check((await page.getByRole('button', { name: /可操作子任务 人工复核/ }).getAttribute('aria-pressed')) === 'true', 'guide selects annotation task');
  await page.getByText('评审与试点：这项工作如何证明价值？', { exact: true }).click();
  check(await page.locator('.task-guide-proof tbody tr').count() === 6, 'six scoring-to-evidence rows');
  check((await page.locator('.task-guide-safety').innerText()).includes('不代表 CVAT/FiftyOne 服务器连接'), 'public guide has current backend and connection boundaries');
  await page.getByRole('heading', { name: '这批数据，下一步需要做什么？' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: 'output/playwright/scoring-business-task-guide.png' });
  const workspaceHref = await page.getByRole('link', { name: '打开公开体验工作簿', exact: true }).getAttribute('href');
  check(workspaceHref === '#/workspace?purpose=annotation-rework', 'workbook link carries purpose not backend task ID');
  await page.getByRole('link', { name: /为这项工作约定试点条件/ }).click();
  await page.getByRole('heading', { name: '先约定一项可以验收的交付' }).waitFor();
  check(await page.getByRole('button', { name: /可操作子任务 人工复核/ }).getAttribute('aria-pressed') === 'true', 'pilot receives selected task');
  const fields = {
    '项目代号': 'TEST-ANNOTATION / 合成验收', '预算负责人角色': '测试交付负责人', '实际使用者角色': '测试标注复核人',
    '项目、批次与产品范围': '仅合成批次与测试框', '最近一次实际问题': '合成浏览器验证，不是客户案例；测试返修版本是否清楚。',
    '授权输入范围': '本地合成输入，无客户资料。', '观察周期与纳入规则': '测试窗口，包含失败与帮助。',
    '对照与独立复核方法': '仅验证草稿功能，业务效果另行独立观察。', '待双方确认的验收条件': '测试字段与选择保持，不得生成生产授权。',
  };
  for (const [label, value] of Object.entries(fields)) await page.getByLabel(label, { exact: false }).fill(value);
  await page.getByRole('button', { name: /持续使用验证 维护下一批/ }).click();
  check(await page.getByLabel('项目代号', { exact: false }).inputValue() === fields['项目代号'], 'switching task preserves user text');
  await page.getByRole('button', { name: /可操作子任务 人工复核/ }).click();
  await page.getByRole('checkbox', { name: /标注返修独立复核通过率/ }).check();
  await page.evaluate(() => {
    const original = URL.createObjectURL;
    URL.createObjectURL = (blob) => { window.__pilotCapture = blob.text(); return original(blob); };
    window.__restorePilotCapture = () => { URL.createObjectURL = original; };
  });
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: '导出试点范围书', exact: true }).click();
  const download = await downloading;
  await download.saveAs('output/playwright/scoring-business-pilot.draft.json');
  const plan = JSON.parse(await page.evaluate(async () => { const text = await window.__pilotCapture; window.__restorePilotCapture(); return text; }));
  check(plan.schema_version === 'industrial-delivery.pilot-plan.v2' && plan.scope.businessTaskId === 'annotation-rework', 'download has v2 bound task');
  check(plan.status === 'DRAFT_NOT_APPROVED' && !plan.production_release_allowed && !plan.machine_write_permitted && plan.measurements.every((metric) => metric.after === null && metric.baseline === null), 'download contains no fabricated result or authority');
  await page.getByLabel('项目代号', { exact: false }).fill('changed');
  await page.locator('input[type=file]').setInputFiles('output/playwright/scoring-business-pilot.draft.json');
  await page.getByText('已读入本地范围书草稿。', { exact: false }).waitFor();
  check(await page.getByLabel('项目代号', { exact: false }).inputValue() === fields['项目代号'], 'v2 reimport restores text');
  await page.getByRole('heading', { name: '先约定一项可以验收的交付' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: 'output/playwright/scoring-business-pilot.png' });
  await page.locator('input[type=file]').setInputFiles('tests/fixtures/commercial_pilot_v1.draft.json');
  await page.getByText('旧版 v1 草稿已按', { exact: false }).waitFor();
  check(page.url().includes('purpose=dataset-acceptance') && (await page.getByLabel('项目代号', { exact: false }).inputValue()).startsWith('LEGACY-TEST'), 'v1 migration is explicit and selects acceptance');
  // Exercise rejected import through the same real file input without writing a forged fixture to disk.
  await page.locator('input[type=file]').evaluate((input) => {
    const transfer = new DataTransfer();
    transfer.items.add(new File([JSON.stringify({ schema_version: 'industrial-delivery.pilot-plan.v2', status: 'APPROVED' })], 'forged.json', { type: 'application/json' }));
    input.files = transfer.files; input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await page.getByRole('alert').waitFor();
  check((await page.getByRole('alert').innerText()).includes('只接受未批准') && (await page.getByLabel('项目代号', { exact: false }).inputValue()).startsWith('LEGACY-TEST'), 'forged approval rejected without destroying draft');
  await page.goto('http://127.0.0.1:4193/#/start?purpose=unknown');
  await page.getByRole('heading', { name: '未找到这个业务任务' }).waitFor();
  check(await page.locator('.task-guide-page .task-guide-primary').count() === 0, 'unknown guide purpose cannot silently select task');
  await page.getByRole('button', { name: /持续使用验证 维护下一批/ }).click();
  check(page.url().includes('purpose=dataset-reuse'), 'unknown purpose is recoverable by explicit selection');
  await page.reload();
  check(await page.getByRole('button', { name: /持续使用验证 维护下一批/ }).getAttribute('aria-pressed') === 'true', 'guide selection persists through reload');
  for (const width of [1366, 1600]) {
    await page.setViewportSize({ width, height: 900 });
    check(await page.locator('.task-guide-page').evaluate((element) => element.scrollWidth <= element.clientWidth + 1), 'desktop guide has no horizontal overflow at ' + width);
  }
  await page.goto('http://127.0.0.1:4193/#/pilot?purpose=unknown');
  await page.getByRole('alert').waitFor();
  check(await page.getByRole('button', { name: '导出试点范围书', exact: true }).isDisabled(), 'unknown pilot purpose blocks export');
  await page.getByRole('button', { name: /可操作子任务 人工复核/ }).click();
  await page.locator('.pilot-plan-page button[type=submit]:enabled').waitFor();
  check(!(await page.getByRole('button', { name: '导出试点范围书', exact: true }).isDisabled()), 'pilot selection recovers export availability');
  check(!/visiondata\s?gate|dukeandbaron/i.test(await page.locator('body').innerText()), 'visible pilot text remains anonymous');
  check(errors.length === 0 && writes.length === 0, 'no browser errors or network writes');
  if (failures.length) throw new Error(failures.join('; '));
  return { passed, failures, errors, writes, checks: passed.length + failures.length, downloadedTask: plan.scope.businessTaskId };
}
