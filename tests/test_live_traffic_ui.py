"""Execute the actual Traffic/Neighbors inline JS with a deterministic scheduler.

The scheduler double implements the shared helper contract; the helper itself is
covered independently by test_live_ui.py. No live broker or public data is used.
"""
import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r"""
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = SOURCE;
const page = PAGE;
const nodes = new Map();
const intervals = [];
const schedulers = [];
const listeners = {};
function element(id) {
  if (!nodes.has(id)) nodes.set(id, {
    value: id === 'status-filter' ? 'all' : '', dataset: {}, style: {},
    classList: {toggle() {}, remove() {}, add() {}}, listeners: {},
    addEventListener(name, fn) {this.listeners[name] = fn;},
    setAttribute() {}, removeAttribute() {}, getAttribute() {return null;},
    append() {}, appendChild() {}, replaceChildren() {},
    getBoundingClientRect() {return {left: 0, top: 0, width: 800, height: 300};}
  });
  return nodes.get(id);
}
const document = {hidden: false, visibilityState: 'visible',
  getElementById: element, documentElement: element('root'),
  addEventListener(name, fn) {listeners[name] = fn;}
};
const window = {addEventListener(name, fn) {listeners[name] = fn;},
  DashboardUI: {createRenderScheduler(callback, options) {
    assert.equal(options.intervalMs, 250);
    const dirty = new Set();
    const scheduler = {
      request(...sections) {sections.forEach(section => dirty.add(section));},
      flush() {if (!document.hidden && dirty.size) {
        const sections = new Set(dirty); dirty.clear(); callback(sections);
      }},
      dispose() {dirty.clear();}
    };
    schedulers.push(scheduler);
    return scheduler;
  }}
};
class WebSocket {
  constructor() {this.listeners = {}; WebSocket.latest = this;}
  addEventListener(name, fn) {this.listeners[name] = fn;}
  close() {}
}
const context = vm.createContext({window, document, WebSocket, console,
  location: {protocol: 'http:', host: 'fixture.invalid'},
  localStorage: {getItem() {return null;}, setItem() {}},
  setInterval(fn, ms) {intervals.push({fn, ms});}, setTimeout() {}, clearTimeout() {}
});
let script = source.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
function replaceOnce(from, to) {
  assert.equal(script.split(from).length, 2, 'startup extraction anchor drift');
  script = script.replace(from, to);
}
if (page === 'traffic') replaceOnce('      init();', '');
else {
  replaceOnce('      connectWebSocket();\n      setInterval', '      setInterval');
  const tail = /      renderAll\(\);\s*$/.exec(script);
  assert.ok(tail, 'startup tail anchor drift');
  script = script.slice(0, tail.index);
}
vm.runInContext(script, context);
const counts = {};
const names = page === 'traffic'
  ? ['renderBroker', 'renderMetrics', 'renderInsights', 'renderLegend', 'renderTalkers', 'renderBursts', 'renderCharts']
  : ['renderMetrics', 'renderGraph', 'renderTable', 'renderDetail'];
for (const name of names) {
  context[name] = (...args) => {counts[name] = (counts[name] || 0) + 1;};
}
function run(code) {return vm.runInContext(code, context);}
function reset() {for (const name of names) counts[name] = 0;}
function tick() {schedulers.forEach(scheduler => scheduler.flush());}
function send(message) {WebSocket.latest.listeners.message({data: JSON.stringify(message)});}
run(page === 'traffic' ? 'init()' : 'connectWebSocket()');
TEST
"""


def execute_page(page, body):
  source = (ROOT / 'backend' / 'static' / f'{page}.html').read_text()
  script = HARNESS.replace('SOURCE', json.dumps(source)).replace('PAGE', json.dumps(page)).replace('TEST', body)
  result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
  if result.returncode:
    raise AssertionError(result.stdout + result.stderr)


class LiveTrafficTests(unittest.TestCase):
  def test_traffic_burst_preserves_every_event_while_coalescing_paints(self):
    execute_page('traffic', r"""
const snapshot = {type: 'snapshot', broker: {connected: true}, traffic: {history_seconds: 180}};
send(snapshot);
assert.equal(counts.renderCharts, 1, 'initial snapshot must paint immediately');
reset();
for (let second = 0; second < 4; second++) {
  for (let i = 1; i <= 25; i++) {
    const total = second * 25 + i;
    send({type: 'traffic_update', traffic: {unique_packets_total: total, history_seconds: 180},
      event: {ts: 1000 + second, route: 'flood', payload: 'message'}});
  }
  assert.equal(counts.renderCharts, second, 'events must not paint before the batch tick');
  tick();
}
assert.equal(counts.renderCharts, 4, '100 events paint only four times');
assert.equal(run('state.traffic.unique_packets_total'), 100);
assert.equal(run('state.traffic.history.reduce((sum, bucket) => sum + bucket.total, 0)'), 100);
assert.equal(run('state.traffic.history.reduce((sum, bucket) => sum + bucket.route_counts.flood, 0)'), 100);
reset();
send({type: 'broker_status', broker: {connected: false}}); tick();
assert.equal(counts.renderBroker, 1);
assert.equal(counts.renderCharts, 0, 'broker status must not redraw charts');
assert.equal(counts.renderTalkers, 0, 'broker status must not rebuild talkers');
document.hidden = true; document.visibilityState = 'hidden';
for (let i = 101; i <= 150; i++) send({type: 'traffic_update',
  traffic: {unique_packets_total: i}, event: {ts: 1005, route: 'direct', payload: 'trace'}});
tick();
assert.equal(counts.renderCharts, 0, 'hidden page must not paint');
assert.equal(run('state.traffic.unique_packets_total'), 150);
assert.equal(run('state.traffic.history.reduce((sum, bucket) => sum + bucket.total, 0)'), 150);
document.hidden = false; document.visibilityState = 'visible'; tick();
assert.equal(counts.renderCharts, 1, 'resume paints latest state only once');
""")

  def test_traffic_interactions_and_age_use_targeted_scheduler(self):
    execute_page('traffic', r"""
reset();
listeners.resize();
element('theme-toggle').listeners.click();
element('route-chart').listeners.mousemove({clientX: 20, clientY: 20});
element('route-chart').listeners.mouseleave();
assert.equal(counts.renderCharts, 0, 'interaction paints must be scheduled');
tick();
assert.equal(counts.renderCharts, 1);
assert.equal(counts.renderTalkers, 0);
reset();
intervals.find(timer => timer.ms === 5000).fn();
assert.equal(counts.renderMetrics, 0, 'age paints must be scheduled');
tick(); assert.equal(counts.renderMetrics, 1);
assert.equal(counts.renderCharts, 0);
""")

  def test_neighbors_batched_topology_targeted_status_and_interactions(self):
    execute_page('neighbors', r"""
const topology = {observers: [], devices: [{device_id: 'fixture-node'}], links: [], stats: {}};
send({type: 'snapshot', broker: {connected: true}, neighbors: topology});
assert.equal(counts.renderGraph, 1, 'snapshot paints immediately');
reset();
run("selectDevice('fixture-node')");
assert.equal(run('state.selected.key'), 'fixture-node');
tick(); reset();
for (let i = 1; i <= 100; i++) send({type: 'neighbors_update', neighbors: {...topology, stats: {links: i}}});
assert.equal(counts.renderGraph, 0, 'topology bursts must not paint per message');
assert.equal(run('state.topology.stats.links'), 100);
tick(); assert.equal(counts.renderGraph, 1);
assert.equal(run('state.selected.key'), 'fixture-node', 'selection survives replacement');
reset();
send({type: 'broker_status', broker: {connected: false}}); tick();
assert.equal(counts.renderMetrics, 1); assert.equal(counts.renderGraph, 0);
reset(); intervals.find(timer => timer.ms === 15000).fn(); tick();
assert.equal(counts.renderTable, 1); assert.equal(counts.renderDetail, 1);
assert.equal(counts.renderGraph, 0, 'age refresh never rebuilds graph');
reset(); document.hidden = true; document.visibilityState = 'hidden';
for (let i = 101; i <= 150; i++) send({type: 'neighbors_update', neighbors: {...topology, stats: {links: i}}});
tick(); assert.equal(counts.renderGraph, 0); assert.equal(run('state.topology.stats.links'), 150);
document.hidden = false; document.visibilityState = 'visible'; tick();
assert.equal(counts.renderGraph, 1);
reset(); element('topology-filter').listeners.input(); tick();
assert.equal(counts.renderGraph, 1, 'filter interaction still updates graph');
reset(); element('status-filter').listeners.change(); tick();
assert.equal(counts.renderTable, 1);
send({type: 'neighbors_update', neighbors: {devices: [], links: [], stats: {}}});
assert.equal(run('state.selected'), null, 'missing selected device is cleared during ingestion');
""")


if __name__ == '__main__':
  unittest.main()
