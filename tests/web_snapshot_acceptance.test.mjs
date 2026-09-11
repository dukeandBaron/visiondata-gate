import test from 'node:test';
import assert from 'node:assert/strict';
import { makeAcceptanceRequirements } from '../web/src/snapshotAcceptance.ts';

const asset = {asset_id:'asset-a',source_sha256:'a'.repeat(64)};
const state = {asset_id:'asset-a',revision:2,document_sha256:'b'.repeat(64),annotations:[{label:'defect'}]};
function input(){return {purpose:'Review the first labeled dataset',vocabulary:'part, defect',reviewer:'Test Reviewer',note:'Reviewed against the labeling standard',attested:true,rows:[{asset,state,split:'train',category:'part',requirement:'REQUIRED'}]};}
test('explicit requirements preserve actual revision and separate category, label and split',()=>{
  const value=makeAcceptanceRequirements(input());
  assert.equal(value.samples[0].human_review.expected_annotation_revision,2);
  assert.equal(value.samples[0].human_review.expected_annotation_sha256,'b'.repeat(64));
  assert.equal(value.samples[0].category,'part');
  assert.equal(value.samples[0].annotation_requirement,'REQUIRED');
  assert.deepEqual(value.category_vocabulary,['defect','part']);
  assert.equal('intended_use' in value,false);
});
test('missing attestation, unknown requirement and missing required annotation are blocked',()=>{
  assert.throws(()=>makeAcceptanceRequirements({...input(),attested:false}),/复核/);
  const x=input();x.rows[0].requirement='UNKNOWN';
  assert.throws(()=>makeAcceptanceRequirements(x),/要求/);
  x.rows[0].requirement='REQUIRED';x.rows[0].state={...state,annotations:[]};
  assert.throws(()=>makeAcceptanceRequirements(x),/标注/);
});
test('vocabulary, scope and not-applicable conflicts are explicit',()=>{
  assert.throws(()=>makeAcceptanceRequirements({...input(),vocabulary:'part'}),/词表/);
  const x=input();x.rows[0].requirement='NOT_APPLICABLE';
  assert.throws(()=>makeAcceptanceRequirements(x),/不适用/);
  x.rows[0].state={...state,asset_id:'other'};
  assert.throws(()=>makeAcceptanceRequirements(x),/版本/);
});
test('optional unlabeled samples require an explicit choice and reviewed revision',()=>{
  const x=input();x.rows[0].requirement='OPTIONAL';x.rows[0].state={...state,annotations:[]};
  assert.equal(makeAcceptanceRequirements(x).samples[0].annotation_requirement,'OPTIONAL');
});
