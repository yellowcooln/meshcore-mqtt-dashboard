const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
let clock = 0;
let sequence = 0;
const timers = new Map();
const listeners = new Map();
class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {};
    this.value = ''; this.checked = false; this.textContent = ''; this.style = {};
    this.parentNode = null; this.events = new Map(); this.classes = new Set();
    this.classList = { add: x => this.classes.add(x), toggle: (x, yes) => yes ? this.classes.add(x) : this.classes.delete(x) };
  }
  set innerHTML(value) { this.html = value; this.children.forEach(x => x.parentNode = null); this.children = []; }
  get innerHTML() { return this.html || ''; }
  get firstChild() { return this.children[0] || null; }
  get nextSibling() { if (!this.parentNode) return null; return this.parentNode.children[this.parentNode.children.indexOf(this) + 1] || null; }
  addEventListener(name, fn) { this.events.set(name, fn); }
  appendChild(el) { return this.insertBefore(el, null); }
  insertBefore(el, before) {
    if (el === before) return el;
    el.remove(); const index = before ? this.children.indexOf(before) : this.children.length;
    this.children.splice(index, 0, el); el.parentNode = this; return el;
  }
  remove() { if (this.parentNode) { const p = this.parentNode; p.children.splice(p.children.indexOf(this), 1); this.parentNode = null; } }
  removeChild(el) { el.remove(); }
  setAttribute(name, value) { this[name] = value; }
  removeAttribute(name) { delete this[name]; }
}
const elements = new Map();
const document = {
  hidden: false, documentElement: new Element('html'),
  getElementById(id) { if (!elements.has(id)) elements.set(id, new Element(id === 'node-table' ? 'tbody' : 'div')); return elements.get(id); },
  createElement(tag) { return new Element(tag); },
  addEventListener(name, fn) { listeners.set(name, fn); },
  removeEventListener(name) { listeners.delete(name); },
};
const sandbox = { console, document, performance: { now: () => clock }, Date, Map, Set,
  location: { protocol: 'http:', host: 'fixture' },
  localStorage: { getItem: () => null, setItem() {} },
  setTimeout(fn, delay) { const id = ++sequence; timers.set(id, { fn, due: clock + Math.max(0, delay) }); return id; },
  clearTimeout(id) { timers.delete(id); }, setInterval() { return 0; },
  addEventListener() {}, removeEventListener() {},
};
sandbox.window = sandbox;
const context = vm.createContext(sandbox);
const shared = path.join(root, 'backend/static/live-ui.js');
if (fs.existsSync(shared)) vm.runInContext(fs.readFileSync(shared, 'utf8'), context);
const html = fs.readFileSync(path.join(root, 'backend/static/index.html'), 'utf8');
let script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
assert.equal((script.match(/      init\(\);/g) || []).length, 1);
script = script.replace('      init();', '      /* Network startup omitted by fixture. */');
vm.runInContext(script, context);
const run = code => vm.runInContext(code, context);
function advance(ms) {
  const end = clock + ms;
  for (;;) {
    const next = [...timers].filter(([, t]) => t.due <= end).sort((a, b) => a[1].due - b[1].due)[0];
    if (!next) break;
    timers.delete(next[0]); clock = next[1].due; next[1].fn();
  }
  clock = end;
}
function visibility(hidden) { document.hidden = hidden; listeners.get('visibilitychange')?.(); }
function instrument(keepNodes = false) {
  run('globalThis.paints={nodes:0,stats:0,detail:0,broker:0,brokerDetail:0,sys:0};');
  for (const [fn, key] of [['renderNodes','nodes'],['renderStats','stats'],['renderNodeDetail','detail'],['renderBroker','broker'],['renderBrokerDetail','brokerDetail'],['renderSys','sys']]) {
    if (keepNodes && fn === 'renderNodes') continue;
    run(`${fn}=()=>{paints.${key}++};`);
  }
}
const mode = process.argv[2];
if (mode === 'burst' || mode === 'hidden') {
  instrument();
  run('applySnapshot({nodes:[],broker:{connected:true},stats:{messages_total:0}})'); advance(1000);
  run('Object.keys(paints).forEach(k=>paints[k]=0)');
  if (mode === 'hidden') visibility(true);
  run('for(let i=1;i<=1000;i++) applyNodeUpdate({node_id:"n"+(i%25),name:"Node "+i,last_seen:i},{messages_total:i})');
  assert.equal(run('state.stats.messages_total'), 1000);
  assert.equal(run('state.nodes.size'), 25);
  if (mode === 'hidden') {
    advance(60000); assert.equal(run('paints.nodes'), 0, 'hidden tabs must not replay paints');
    visibility(false); advance(250);
    assert.equal(run('paints.nodes'), 1, 'resume should paint latest state once');
  } else {
    advance(1000);
    assert.ok(run('paints.nodes') >= 1 && run('paints.nodes') <= 4, '1000 updates should use at most four node paints');
  }
  assert.equal(run('paints.broker'), 0, 'node updates must not rebuild broker panel');
  assert.equal(run('paints.brokerDetail'), 0);
  assert.equal(run('paints.sys'), 0);
  console.log(JSON.stringify({mode, processed:run('state.stats.messages_total'), paints:run('paints')}));
} else if (mode === 'cadence') {
  instrument();
  run('applySnapshot({nodes:[],broker:{connected:true},stats:{messages_total:0}})'); advance(1000);
  run('globalThis.paintTimes=[];renderNodes=()=>{paintTimes.push(performance.now())};');
  for (let i=1;i<=1000;i++) {
    run(`applyNodeUpdate({node_id:"n",name:"Node",last_seen:${i}},{messages_total:${i}})`);
    advance(1);
  }
  advance(250);
  const times = run('paintTimes');
  assert.ok(times.length > 1 && times.length <= 5);
  for (let i=1;i<times.length;i++) assert.ok(times[i]-times[i-1]>=250, 'successive paints must be 250ms apart');
  assert.equal(run('state.stats.messages_total'), 1000);
  console.log(JSON.stringify({mode, processed:1000, paintTimes:times}));
} else if (mode === 'stable') {
  instrument(true);
  run('applySnapshot({broker:{},nodes:[{node_id:"z",name:"Zulu",last_seen:Date.now()/1000},{node_id:"a",name:"Alpha",last_seen:Date.now()/1000-1}]})'); advance(1000);
  const table = elements.get('node-table');
  assert.equal(table.children[0].children[1].textContent, 'Alpha', 'default sort must be stable by name');
  const alpha = table.children[0];
  run('applyNodeUpdate({node_id:"z",name:"Zulu",last_seen:Date.now()/1000+1},{messages_total:1})'); advance(250);
  assert.equal(table.children[0], alpha, 'unchanged rows must retain DOM identity');
  assert.equal(table.children[0].children[1].textContent, 'Alpha');
  elements.get('node-sort').value = 'recent'; run('renderNodes()');
  assert.equal(table.children[0].children[1].textContent, 'Zulu', 'recent-first must remain available');
  console.log(JSON.stringify({mode, stableRows:true, recentSort:true}));
} else { throw new Error('Unknown mode'); }
