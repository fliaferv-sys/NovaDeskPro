const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../../../static/shared/js/institutional_identity.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

function setup(configs = [{}]) {
    let focused;
    const requests = [];
    const timers = new Map();
    const jqueryListeners = new Map();
    let timerId = 0;
    class Element {
        constructor(name = '', value = '', tagName = 'INPUT') { this.name = name; this.value = value; this.tagName = tagName; this.listeners = {}; this.children = []; this.options = [{value: ''}, {value: 'PERMANENT'}, {value: 'OUTSOURCED'}]; this.attrs = {}; this.hidden = false; this.textContent = ''; }
        addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
        dispatchEvent(event) { event.target ||= this; for (const fn of this.listeners[event.type] || []) fn(event); }
        emit(type, key) { this.dispatchEvent({type, key, preventDefault() {}}); }
        add(option) { this.options.push(option); }
        appendChild(node) { this.children.push(node); }
        replaceChildren() { this.children = []; }
        setAttribute(key, value) { this.attrs[key] = value; }
        checkValidity() { return true; }
        focus() { focused = this; }
        querySelector(selector) { return this.children[0] || null; }
        querySelectorAll() { return this.children; }
    }
    const instances = configs.map(config => {
        const selectors = {};
        for (const name of ['query', 'field', 'results', 'status', 'reference', 'search', 'clear']) selectors['[data-identity-' + name + ']'] = new Element();
        selectors['[data-identity-field]'].value = 'email';
        const mapping = config.mapping || Object.fromEntries(['email', 'username', 'first_name', 'last_name', 'phone', 'employment_type', 'department'].map(key => [key, key]));
        selectors['script[type="application/json"]'] = {textContent: JSON.stringify(mapping)};
        const elements = {};
        for (const name of [...new Set([...Object.values(mapping), 'email', 'username', 'first_name', 'last_name', 'phone', 'employment_type', 'department', 'password1', 'password2', 'role'])]) {
            elements[name] = new Element(name, config.initial?.[name] ?? (name === 'employment_type' ? 'PERMANENT' : ''), ['employment_type', 'department'].includes(name) ? 'SELECT' : 'INPUT');
        }
        const form = {elements: [...Object.values(elements), new Element('csrfmiddlewaretoken', 'csrf')]};
        const container = {dataset: {mode: config.mode || 'add', context: 'accounts.' + (config.mode || 'add'), objectId: config.mode === 'change' ? 'test-id' : '', bound: String(config.bound || false), explicitOnly: String(config.explicitOnly || false), clearFields: String(config.clearFields || false), searchUrl: '/search', resolveUrl: '/resolve'}, closest: () => form, querySelector: selector => selectors[selector]};
        return {container, selectors, elements, control: name => selectors['[data-identity-' + name + ']']};
    });
    const document = {readyState: 'complete', querySelectorAll: () => instances.map(i => i.container), createElement: () => new Element('', '', 'BUTTON')};
    const window = {setTimeout(fn) { const id = ++timerId; timers.set(id, fn); return id; }, clearTimeout(id) { timers.delete(id); }, django: {jQuery: element => ({on(name, fn) { jqueryListeners.set(element, fn); }, trigger() {}})}};
    vm.runInNewContext(source, {window, document, AbortController, Event: class {constructor(type) {this.type = type;}}, Option: class {constructor(label, value) {this.label = label; this.value = value;}}, fetch: (url, options) => new Promise(resolve => requests.push({url, options, resolve}))});
    return {instances, requests, timers, jqueryListeners, window, focused: () => focused, async resolve(index, data, ok = true) { requests[index].resolve({ok, json: async () => data}); await tick(); }, flushTimers() { const callbacks = [...timers.values()]; timers.clear(); callbacks.forEach(fn => fn()); }};
}
const identity = {reference: 'signed-ref'};
const found = {status: 'resolved', identity, values: {email: 'person@petropar.gov.py', username: 'person', first_name: 'Nombre', last_name: 'Apellido', phone: '123', employment_type: 'OUTSOURCED', department: {value: '17', label: 'Dependencia'}, password1: 'NEVER', role: 'ADMIN'}};
const candidate = {reference: 'candidate-ref', full_name: 'Nombre Apellido', email: 'person@petropar.gov.py', source: 'RRHH'};
function search(h, index = 0) { const i = h.instances[index]; i.control('query').value = 'person@petropar.gov.py'; i.control('search').emit('click'); return i; }

test('alta exacta completes fields, derives username and never touches passwords or roles', async () => {
    const h = setup(); const i = search(h);
    assert.equal(i.control('status').textContent, 'Buscando datos institucionales...');
    assert.equal(h.requests[0].options.method, 'POST');
    assert.equal(h.requests[0].options.headers['X-CSRFToken'], 'csrf');
    await h.resolve(0, found);
    assert.equal(i.elements.username.value, 'person');
    assert.equal(i.elements.first_name.value, 'Nombre');
    assert.equal(i.elements.employment_type.value, 'OUTSOURCED');
    assert.equal(i.elements.department.value, '17');
    assert.equal(i.elements.password1.value, ''); assert.equal(i.elements.password2.value, ''); assert.equal(i.elements.role.value, '');
});

test('manual edits during a request and initial values are protected', async () => {
    const h = setup([{initial: {username: 'manual', last_name: 'Manual'}}]); const i = search(h);
    i.elements.first_name.value = 'Edited'; i.elements.first_name.emit('input');
    i.elements.phone.emit('input');
    await h.resolve(0, found);
    assert.equal(i.elements.username.value, 'manual'); assert.equal(i.elements.last_name.value, 'Manual');
    assert.equal(i.elements.first_name.value, 'Edited'); assert.equal(i.elements.phone.value, '');
    assert.match(i.control('status').textContent, /conservaron/);
});

test('edit opens without requests or replacements, then requires explicit selection', async () => {
    const h = setup([{mode: 'change', initial: {first_name: 'Original', email: 'old@petropar.gov.py'}}]); const i = h.instances[0];
    assert.equal(h.requests.length, 0); assert.equal(i.elements.first_name.value, 'Original');
    search(h); await h.resolve(0, {...found, candidates: [candidate]});
    assert.equal(i.elements.first_name.value, 'Original');
    i.control('results').children[0].emit('click');
    assert.equal(h.requests[1].url, '/resolve'); await h.resolve(1, found);
    assert.equal(i.elements.first_name.value, 'Nombre'); assert.equal(i.elements.email.value, 'person@petropar.gov.py');
    assert.match(i.control('status').textContent, /Persona seleccionada/);
});

test('explicit selection may replace manual values but leaves passwords untouched', async () => {
    const h = setup([{initial: {first_name: 'Manual'}}]); const i = search(h);
    await h.resolve(0, {status: 'candidates', candidates: [candidate]}); i.control('results').children[0].emit('click');
    await h.resolve(1, found); assert.equal(i.elements.first_name.value, 'Nombre'); assert.equal(i.elements.password1.value, '');
});

test('debounce and sequence checks ignore obsolete responses', async () => {
    const h = setup(); const i = search(h);
    i.control('query').value = 'other'; i.control('query').emit('input');
    i.control('query').value = 'latest'; i.control('query').emit('input');
    assert.equal(h.timers.size, 1); h.flushTimers();
    assert.equal(h.requests.length, 2); assert.equal(JSON.parse(h.requests[1].options.body).q, 'latest');
    await h.resolve(0, found); assert.equal(i.elements.first_name.value, '');
    await h.resolve(1, {status: 'not_found', candidates: []}); assert.match(i.control('status').textContent, /No se encontraron/);
});

test('changing email invalidates selection and clears only automatically owned fields', async () => {
    const h = setup(); const i = search(h); await h.resolve(0, found);
    i.elements.first_name.value = 'Manual'; i.elements.first_name.emit('input');
    i.elements.email.value = 'next@petropar.gov.py'; i.elements.email.emit('input');
    assert.equal(i.control('reference').value, ''); assert.equal(i.elements.username.value, ''); assert.equal(i.elements.first_name.value, 'Manual');
    i.elements.email.emit('blur'); assert.equal(h.requests.length, 2);
});

test('multiple instances have independent mapped fields and requests', async () => {
    const h = setup([{}, {mapping: {full_name: 'recipient_name', email: 'recipient_email'}}]);
    const a = search(h, 0); const b = search(h, 1);
    await h.resolve(1, {...found, values: {full_name: 'Recipient', email: 'recipient@petropar.gov.py'}});
    assert.equal(b.elements.recipient_name.value, 'Recipient'); assert.equal(a.elements.first_name.value, '');
    await h.resolve(0, found); assert.equal(a.elements.first_name.value, 'Nombre');
    h.window.NovaDeskIdentity.initialize(); assert.equal(h.requests.length, 2);
});

test('candidate keyboard navigation, Escape and manual continuation', async () => {
    const h = setup(); const i = search(h);
    await h.resolve(0, {status: 'candidates', candidates: [candidate, {...candidate, email: 'other@petropar.gov.py'}]});
    i.control('query').emit('keydown', 'ArrowDown'); assert.equal(h.focused(), i.control('results').children[0]);
    i.control('results').dispatchEvent({type: 'keydown', key: 'ArrowDown', target: i.control('results').children[0], preventDefault() {}});
    assert.equal(h.focused(), i.control('results').children[1]);
    i.control('results').emit('keydown', 'Escape'); assert.equal(i.control('results').hidden, true); assert.equal(h.focused(), i.control('query'));
    i.control('clear').emit('click'); assert.match(i.control('status').textContent, /carga manual/);
});

test('bound forms, Select2 edits and unsafe mappings remain protected', async () => {
    const h = setup([{bound: true, mapping: {first_name: 'first_name', employment_type: 'employment_type', username: 'password1'}}]); const i = search(h);
    await h.resolve(0, {...found, candidates: [candidate]}); assert.equal(i.elements.first_name.value, '');
    const j = setup(); const k = search(j); k.elements.department.value = 'manual'; j.jqueryListeners.get(k.elements.department)();
    await j.resolve(0, found); assert.equal(k.elements.department.value, 'manual');
    const unsafe = setup([{mapping: {username: 'password1'}}]); const u = search(unsafe); await unsafe.resolve(0, found); assert.equal(u.elements.password1.value, '');
});

test('errors and incomplete searches never autocomplete', async () => {
    const h = setup(); const i = search(h); await h.resolve(0, {}, false); assert.match(i.control('status').textContent, /No fue posible/);
    search(h); await h.resolve(1, {status: 'candidates', incomplete: true, candidates: [candidate]});
    assert.equal(i.elements.first_name.value, ''); assert.match(i.control('status').textContent, /incompleta/);
});


test('manual edits made after explicit selection starts survive the late response', async () => {
    const h = setup([{mode: 'change', initial: {first_name: 'Original'}}]); const i = search(h);
    await h.resolve(0, {status: 'candidates', candidates: [candidate]});
    i.control('results').children[0].emit('click');
    i.elements.first_name.value = 'Edited during selection'; i.elements.first_name.emit('input');
    await h.resolve(1, found);
    assert.equal(i.elements.first_name.value, 'Edited during selection');
    assert.match(i.control('status').textContent, /durante la consulta/);
    assert.equal(h.focused(), i.control('query'));
});

test('new search removes old automatic values but keeps manual fields', async () => {
    const h = setup(); const i = search(h); await h.resolve(0, found);
    i.elements.first_name.value = 'Manual'; i.elements.first_name.emit('input');
    i.control('query').value = 'different'; i.control('query').emit('input');
    assert.equal(i.elements.username.value, ''); assert.equal(i.elements.first_name.value, 'Manual');
    assert.equal(i.control('reference').value, '');
});


test('printing exact search requires selection and maps only local responsible', async () => {
    const h = setup([{explicitOnly: true, mapping: {local_user_id: 'responsible_user'}}]);
    const i = search(h);
    await h.resolve(0, {...found, candidates: [candidate], values: {local_user_id: 'local-1'}});
    assert.equal(i.elements.responsible_user.value, '');
    assert.equal(i.control('results').children.length, 1);
    i.control('results').children[0].emit('click');
    await h.resolve(1, {status: 'resolved', identity: {reference: 'printing-ref'}, values: {local_user_id: {value: 'local-1', label: 'Persona Local'}}});
    assert.equal(i.elements.responsible_user.value, 'local-1');
    assert.equal(i.control('reference').value, 'printing-ref');
    assert.equal(i.elements.password1.value, '');
});

test('printing identity without local account preserves existing responsible', async () => {
    const h = setup([{mode: 'change', explicitOnly: true, mapping: {local_user_id: 'responsible_user'}, initial: {responsible_user: 'existing'}}]);
    const i = search(h);
    await h.resolve(0, {status: 'candidates', candidates: [candidate]});
    i.control('results').children[0].emit('click');
    await h.resolve(1, {status: 'unassignable', message: 'Sin cuenta local asociable'});
    assert.equal(i.elements.responsible_user.value, 'existing');
    assert.equal(i.control('reference').value, '');
    assert.equal(i.control('status').textContent, 'Sin cuenta local asociable');
});

test('printing clear removes assigned user and never searches on edit open', () => {
    const h = setup([{mode: 'change', clearFields: true, explicitOnly: true, mapping: {local_user_id: 'responsible_user'}, initial: {responsible_user: 'existing'}}]);
    const i = h.instances[0];
    assert.equal(h.requests.length, 0);
    assert.equal(i.elements.responsible_user.value, 'existing');
    i.control('clear').emit('click');
    assert.equal(i.elements.responsible_user.value, '');
    assert.equal(i.control('reference').value, '');
});
