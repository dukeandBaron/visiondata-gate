import assert from 'node:assert/strict';
import test from 'node:test';
import { sidebarSections, workbenchTabKey, validWorkbenchTabs } from '../web/src/workbenchNavigation.ts';

test('daily navigation is five tasks while records, guides and advanced routes remain reachable',()=>{
 const groups=sidebarSections(false);
 assert.deepEqual(groups[0].paths,['/workspace','/command-center','/data-pools','/models','/capa']);
 assert.equal(groups.slice(1).every(g=>g.collapsible),true);
 const paths=groups.flatMap(g=>g.paths);
 for(const p of ['/platform','/learning','/compute','/cases','/evidence','/runs','/lineage','/start','/pilot','/governance','/review'])assert.ok(paths.includes(p));
 assert.equal(new Set(paths).size,paths.length);
});
test('public replay never offers local training, pool or compute routes',()=>{
 const paths=sidebarSections(true).flatMap(g=>g.paths);
 for(const p of ['/models','/data-pools','/learning','/compute','/platform'])assert.equal(paths.includes(p),false);
});
test('only known same-origin page hints survive, with exact deep-link query and hash preserved',()=>{
 const good='/models?tab=vision&pool=pool_test#history';
 assert.deepEqual(validWorkbenchTabs([good,'/cases/case_test?task=task_test','//evil.example','https://evil.example','/missing','/workspace/../unknown',1],false),[good,'/cases/case_test?task=task_test']);
 assert.deepEqual(validWorkbenchTabs(['/models?tab=vision','/workspace'],true),['/workspace']);
 assert.deepEqual(validWorkbenchTabs('bad',false),['/workspace']);
});
test('open page hints are isolated by account and public/local mode',()=>{
 assert.notEqual(workbenchTabKey('user_a',false),workbenchTabKey('user_b',false));
 assert.notEqual(workbenchTabKey('user_a',false),workbenchTabKey('user_a',true));
 assert.equal(workbenchTabKey(undefined,false).includes('anonymous'),true);
});
