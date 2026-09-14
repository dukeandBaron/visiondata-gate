import assert from 'node:assert/strict';
import test from 'node:test';
import { readInterfacePreferences, saveInterfacePreferences } from '../web/src/interfacePreferences.ts';
const data=new Map();
globalThis.document={documentElement:{dataset:{}}};
globalThis.window={localStorage:{getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v)},dispatchEvent:()=>{}};
test('neutral graphite is the fresh default without manufacturing preference choices',()=>{
 data.clear();assert.equal(readInterfacePreferences().accent,'graphite');
});
test('legacy appearance migrates only palette; density and motion choices survive',()=>{
 data.clear();data.set('visiondata:interface-preferences',JSON.stringify({accent:'cyan-lime',density:'compact',reduceMotion:true}));
 assert.deepEqual(readInterfacePreferences(),{accent:'graphite',density:'compact',reduceMotion:true});
});
test('new explicit palette choice persists, corrupt values fall back safely',()=>{
 data.clear();saveInterfacePreferences({accent:'coral-violet',density:'compact',reduceMotion:false});
 assert.equal(readInterfacePreferences().accent,'coral-violet');
 data.set('visiondata:interface-preferences:v2','bad-json');assert.equal(readInterfacePreferences().accent,'graphite');
});
