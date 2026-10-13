const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../../../static/tickets/js/technical_context.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

function setup(mobile = false, automatic = false, client = false) {
    class Element {
        constructor() { this.children = []; this.listeners = {}; this.value = ''; this.textContent = ''; }
        appendChild(node) { this.children.push(node); }
        replaceChildren() { this.children = []; }
        addEventListener(type, handler) { this.listeners[type] = handler; }
        dispatchEvent(event) { this.listeners[event.type]?.(event); }
        click() { this.listeners.click?.(); }
    }
    const description = new Element(); description.value = 'Texto manual';
    const asset = new Element(); asset.options = [{value: ''}, {value: 'owned-id'}];
    const nodes = Object.fromEntries(['status', 'results', 'query', 'load', 'clear', 'selection'].map(name => [`[data-context-${name}]`, new Element()]));
    const panel = {dataset: {url: '/tickets/contexto-tecnico/', ...(automatic ? {autoUrl: '/tickets/contexto-automatico/'} : {}), ...(client ? {contextClient: 'true'} : {})}, querySelector: selector => nodes[selector], closest: () => ({querySelector: selector => selector.includes('description') ? description : asset})};
    const requests = [];
    vm.runInNewContext(source, {document: {querySelectorAll: () => [panel], createElement: () => new Element()},
        window: {location: {origin: 'http://novadesk.test'}, matchMedia: () => ({matches: mobile})},
        URL, AbortController, Event: class {constructor(type) {this.type = type;}},
        fetch: (url, options) => new Promise(resolve => requests.push({url, options, resolve}))});
    return {nodes, description, asset, requests, async resolve(index, data) { requests[index].resolve({ok: true, json: async () => data}); await tick(); }};
}
const context = {review_token: 'signed-reference', requester: {full_name: 'Solicitante'}, person: {candidates: []}, warnings: [], devices: [{
    data: {name: 'Equipo detectado'}, provenance: {name: 'GLPI'}, confidence: 'CONFIRMADA', ip: '192.0.2.1',
    detected_user: {candidates: [{data: {full_name: 'Usuario diferente'}, confidence: 'PROBABLE'}]},
    novadesk_assets: [{id: 'owned-id', code: 'A-1', can_select: true, responsible: {full_name: 'Custodio distinto'}}]
}]};
function flatten(node) {return [node, ...node.children.flatMap(flatten)];}

test('late suggestions preserve manual description and asset until explicit review', async () => {
    const h = setup(); h.description.value = 'Edición mientras consulta';
    assert.equal(h.requests.length, 0);
    h.nodes['[data-context-query]'].value = '192.0.2.1'; h.nodes['[data-context-load]'].click();
    await h.resolve(0, context);
    assert.equal(h.description.value, 'Edición mientras consulta'); assert.equal(h.asset.value, '');
    const buttons = flatten(h.nodes['[data-context-results]']);
    assert.ok(buttons.some(node => node.textContent.includes('Custodio distinto')));
    assert.ok(buttons.some(node => node.textContent.includes('Usuario diferente')));
    buttons.find(node => node.textContent.startsWith('Seleccionar equipo')).click();
    assert.ok(h.description.value.startsWith('Edición mientras consulta'));
    assert.doesNotMatch(h.description.value, /NOVADESK_TECHNICAL_CONTEXT_V1/);
    assert.equal(JSON.parse(h.nodes['[data-context-selection]'].value).device, 0);
    assert.equal(h.asset.value, '');
});
test('unrelated custodian never changes the ticket asset', async () => {
    const h = setup(); const data = structuredClone(context); data.devices[0].novadesk_assets[0].can_select = false;
    h.nodes['[data-context-query]'].value = '192.0.2.1'; h.nodes['[data-context-load]'].click();
    await h.resolve(0, data);
    assert.equal(h.nodes['[data-context-selection]'].value, '');
    assert.equal(h.asset.value, '');
});
test('old responses cannot replace latest suggestions', async () => {
    const h = setup(); h.nodes['[data-context-query]'].value = '192.0.2.1'; h.nodes['[data-context-load]'].click();
    h.nodes['[data-context-query]'].value = '192.0.2.2'; h.nodes['[data-context-load]'].click();
    assert.ok(h.requests[0].options.signal.aborted);
    const latest = structuredClone(context); latest.devices[0].data.name = 'Último equipo';
    await h.resolve(1, latest); await h.resolve(0, context);
    assert.match(flatten(h.nodes['[data-context-results]']).map(node => node.textContent).join(' '), /Último equipo/);
});
test('mobile does not start new requests', () => {
    const h = setup(true); assert.equal(h.requests.length, 0);
});

test('empty query never fetches and multiple devices require review', async () => {
    const h = setup(); h.nodes['[data-context-load]'].click();
    assert.equal(h.requests.length, 0);
    h.nodes['[data-context-query]'].value = 'pc-test'; h.nodes['[data-context-load]'].click();
    const data = structuredClone(context); data.devices.push(structuredClone(data.devices[0]));
    await h.resolve(0, data);
    assert.equal(h.nodes['[data-context-selection]'].value, '');
    const buttons = flatten(h.nodes['[data-context-results]']).filter(node => node.textContent.startsWith('Seleccionar equipo'));
    assert.equal(buttons.length, 2); buttons[1].click();
    assert.equal(JSON.parse(h.nodes['[data-context-selection]'].value).device, 1);
    h.nodes['[data-context-query]'].dispatchEvent({type: 'input'});
    assert.equal(h.nodes['[data-context-selection]'].value, 'skip');
    buttons[0].click(); assert.equal(h.nodes['[data-context-selection]'].value, 'skip');
});

test('removing reviewed context leaves manual description intact', async () => {
    const h = setup(); h.nodes['[data-context-query]'].value = '192.0.2.1'; h.nodes['[data-context-load]'].click();
    await h.resolve(0, context);
    flatten(h.nodes['[data-context-results]']).find(node => node.textContent.startsWith('Seleccionar equipo')).click();
    h.nodes['[data-context-clear]'].click();
    assert.equal(h.nodes['[data-context-selection]'].value, 'skip');
    assert.equal(h.description.value, 'Texto manual');
});

test('staff automatically fetches once and prepares only server-approved selection', async () => {
    const h = setup(false, true);
    assert.equal(h.requests.length, 1);
    const data = structuredClone(context); data.automatic_selection = {device: 0, requester: null, detected: null, asset: 0};
    await h.resolve(0, data);
    assert.equal(JSON.parse(h.nodes['[data-context-selection]'].value).device, 0);
    assert.equal(h.requests.length, 1); assert.equal(h.asset.value, '');
    assert.equal(h.description.value, 'Texto manual');
});

test('automatic ambiguity never silently selects a device', async () => {
    const h = setup(false, true); const data = structuredClone(context);
    data.devices.push(structuredClone(data.devices[0]));
    await h.resolve(0, data);
    assert.equal(h.nodes['[data-context-selection]'].value, '');
});

test('client including mobile gets only a simple automatic status', async () => {
    const h = setup(true, true, true);
    await h.resolve(0, {device_name: 'PC601', review_token: 'proof', automatic_selection: {device: 0, asset: 0}});
    assert.match(h.nodes['[data-context-status]'].textContent, /PC601/);
    assert.equal(h.nodes['[data-context-results]'].children.length, 0);
    assert.equal(h.description.value, 'Texto manual');
});
