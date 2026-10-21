// Browser script boundary regression for baseline 57cfcdc6867f.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync(0, 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function element() {
  return {
    textContent: '', style: {}, dataset: {}, children: [], value: '', disabled: false,
    listeners: {},
    appendChild(child) { this.children.push(child); },
    replaceChildren() { this.children = []; },
    addEventListener(event, callback) { this.listeners[event] = callback; },
  };
}

function createPortal() {
  const elements = new Map();
  const timers = [];
  const redirects = [];
  const document = {
    createElement: element,
    querySelectorAll() { return []; },
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, element());
      return elements.get(id);
    },
  };
  let xhr;
  const context = vm.createContext({
    document,
    window: { location: { replace(url) { redirects.push(url); } } },
    setTimeout(callback, delay) { timers.push({ callback, delay }); },
    XMLHttpRequest: class {
      constructor() { xhr = this; }
      open(method, url) { this.method = method; this.url = url; }
      setRequestHeader() {}
      send(body) { this.body = body; }
    },
  });
  vm.runInContext(script, context);
  return {
    document, context, timers, redirects,
    get xhr() { return xhr; },
  };
}

for (const response of [
  { status: 403, body: { success: false, message: 'Setup access denied' }, error: 'Setup access denied' },
  { status: 503, body: { success: false, message: 'Unable to stop hotspot' }, error: 'Unable to stop hotspot' },
  { status: 500, body: { networks: [] }, error: 'Rescan failed.' },
  { status: 200, body: {}, error: 'Rescan failed.' },
  { status: 200, body: { networks: [] } },
  { timeout: true, error: 'Rescan timed out. Try again.' },
]) {
  const portal = createPortal();
  const { document, context } = portal;
  const initialNetworks = context.networks;
  context.rescan();
  const xhr = portal.xhr;
  if (response.timeout) {
    assert.equal(typeof xhr.ontimeout, 'function');
    xhr.ontimeout();
  } else {
    xhr.status = response.status;
    xhr.responseText = JSON.stringify(response.body);
    xhr.onload();
  }
  assert.equal(document.getElementById('rescanBtn').disabled, false);
  const status = document.getElementById('status');
  if (response.error) {
    assert.equal(status.textContent, response.error);
    assert.equal(status.className, 'status error');
    assert.equal(status.style.display, 'block');
    assert.equal(context.networks, initialNetworks, 'failed scans retain the previous list');
  } else {
    assert.equal(status.style.display, 'none');
    assert.equal(context.networks.length, 0);
  }
}

for (const ssid of [' Network ', '   ']) {
  const portal = createPortal();
  const input = portal.document.getElementById('manualSsid');
  input.value = ssid;
  input.listeners.input.call(input);
  portal.context.connectWifi();
  assert.equal(JSON.parse(portal.xhr.body).ssid, ssid, 'manual SSIDs retain every byte');
}

function startConnection() {
  const portal = createPortal();
  const manualSsid = portal.document.getElementById('manualSsid');
  manualSsid.value = 'Venue Wi-Fi';
  manualSsid.listeners.input.call(manualSsid);
  portal.document.getElementById('wifiPassword').value = 'correct horse battery';
  portal.context.connectWifi();
  assert.equal(portal.xhr.method, 'POST');
  assert.equal(portal.xhr.url, '/api/connect');
  assert.deepEqual(JSON.parse(portal.xhr.body), {
    ssid: 'Venue Wi-Fi', password: 'correct horse battery',
  });
  assert.equal(portal.document.getElementById('connectBtn').disabled, true);
  assert.equal(portal.document.getElementById('rescanBtn').disabled, true);
  const status = portal.document.getElementById('status');
  assert.equal(status.textContent, 'Connecting to Venue Wi-Fi...');
  assert.equal(status.className, 'status connecting');
  assert.equal(status.style.display, 'block');
  return portal;
}

function assertConnectionRejected(portal, response) {
  const xhr = portal.xhr;
  xhr.status = response.status;
  xhr.responseText = response.body;
  xhr.onload();
  const status = portal.document.getElementById('status');
  assert.equal(status.textContent, response.message);
  assert.equal(status.className, 'status error');
  assert.equal(status.style.display, 'block');
  assert.equal(portal.document.getElementById('connectBtn').disabled, false);
  assert.equal(portal.document.getElementById('rescanBtn').disabled, false);
  assert.deepEqual(portal.redirects, []);
}

{
  const portal = startConnection();
  const xhr = portal.xhr;
  assert.equal(xhr.timeout, 45000);
  xhr.status = 200;
  xhr.responseText = JSON.stringify({ success: true });
  xhr.onload();
  const status = portal.document.getElementById('status');
  assert.equal(status.textContent, 'Connected! Redirecting...');
  assert.equal(status.className, 'status success');
  assert.equal(status.style.display, 'block');
  assert.equal(portal.document.getElementById('connectBtn').disabled, true);
  assert.equal(portal.document.getElementById('rescanBtn').disabled, true);
  assert.deepEqual(portal.redirects, []);
  assert.equal(portal.timers.length, 1);
  assert.equal(portal.timers[0].delay, 2000);
  portal.timers[0].callback();
  assert.deepEqual(portal.redirects, ['/']);
}

{
  const portal = startConnection();
  assertConnectionRejected(portal, {
    status: 200,
    body: JSON.stringify({ success: false, message: 'Wrong password' }),
    message: 'Wrong password',
  });
}

{
  const portal = startConnection();
  assertConnectionRejected(portal, {
    status: 503,
    body: JSON.stringify({ success: false, message: 'Unable to start Wi-Fi connection' }),
    message: 'Unable to start Wi-Fi connection',
  });
}

{
  const portal = startConnection();
  assertConnectionRejected(portal, {
    status: 200,
    body: '{invalid JSON',
    message: 'Unexpected error. Try again.',
  });
}

{
  const portal = startConnection();
  portal.xhr.onerror();
  const status = portal.document.getElementById('status');
  assert.equal(status.textContent, 'Request failed. Hotspot may be restarting.');
  assert.equal(status.className, 'status error');
  assert.equal(status.style.display, 'block');
  assert.equal(portal.document.getElementById('connectBtn').disabled, true);
  assert.equal(portal.document.getElementById('rescanBtn').disabled, true);
  assert.equal(portal.timers.length, 1);
  assert.equal(portal.timers[0].delay, 5000);
  portal.timers[0].callback();
  assert.deepEqual(portal.redirects, ['/']);
}

{
  const portal = startConnection();
  assert.equal(portal.xhr.timeout, 45000);
  portal.xhr.ontimeout();
  const status = portal.document.getElementById('status');
  assert.equal(status.textContent, 'Timed out. Check password and try again.');
  assert.equal(status.className, 'status error');
  assert.equal(status.style.display, 'block');
  assert.equal(portal.document.getElementById('connectBtn').disabled, false);
  assert.equal(portal.document.getElementById('rescanBtn').disabled, false);
  assert.deepEqual(portal.redirects, []);
}
