/* Shared identity selector. Each container owns its requests and field state. */
(() => {
    const initialized = new WeakSet();
    let instanceId = 0;
    const allowed = new Set(['email', 'username', 'first_name', 'last_name', 'document_number', 'employee_number', 'phone', 'position', 'employment_type', 'department', 'organizational_unit', 'name', 'full_name', 'location', 'employment_relationship', 'local_user_id', 'rrhh_id']);
    const forbidden = /password|permission|groups|role|is_staff|is_superuser|is_active|approval|audit|created_by|updated_by/i;
    function init(container) {
        if (initialized.has(container)) return;
        const form = container.closest('form');
        const query = container.querySelector('[data-identity-query]');
        const field = container.querySelector('[data-identity-field]');
        const results = container.querySelector('[data-identity-results]');
        const status = container.querySelector('[data-identity-status]');
        const reference = container.querySelector('[data-identity-reference]');
        const mapNode = container.querySelector('script[type="application/json"]');
        if (!form || !query || !field || !results || !status || !reference || !mapNode) return;
        let mapping;
        try { mapping = JSON.parse(mapNode.textContent); } catch { return; }
        initialized.add(container);
        results.id = 'institutional-identity-results-' + (++instanceId);
        results.setAttribute('role', 'group');
        results.setAttribute('aria-label', 'Personas encontradas');
        query.setAttribute('aria-controls', results.id);
        let applying = false;
        let controller;
        let sequence = 0;
        let timer;
        const states = new Map();
        Object.entries(mapping).forEach(([key, name]) => {
            if (!allowed.has(key) || typeof name !== 'string' || forbidden.test(name)) return;
            const input = Array.from(form.elements).find(element => element.name === name);
            if (!input) return;
            const pristineDefault = key === 'employment_type' && container.dataset.mode === 'add' && container.dataset.bound !== 'true';
            const state = {input, initial: input.value, manual: !!input.value && !pristineDefault, filled: null, revision: 0};
            states.set(key, state);
            const mark = () => { if (!applying) { state.manual = true; state.revision++; } };
            input.addEventListener('input', mark);
            input.addEventListener('change', mark);
            if (window.django?.jQuery && input.tagName === 'SELECT') window.django.jQuery(input).on('change.institutionalIdentity', mark);
        });
        const emailInput = states.get('email')?.input;
        function cancel() {
            sequence++;
            window.clearTimeout(timer);
            controller?.abort();
        }
        function setStatus(message) { status.textContent = message; }
        function clearResults() { results.replaceChildren(); results.hidden = true; query.setAttribute('aria-expanded', 'false'); }
        function setValue(state, suggestion) {
            const value = String(typeof suggestion === 'object' ? suggestion.value : suggestion);
            applying = true;
            try {
                if (state.input.tagName === 'SELECT' && !Array.from(state.input.options).some(option => option.value === value)) {
                    if (!suggestion.label) return false;
                    state.input.add(new Option(suggestion.label, value));
                }
                state.input.value = value;
                state.input.dispatchEvent(new Event('input', {bubbles: true}));
                state.input.dispatchEvent(new Event('change', {bubbles: true}));
                if (window.django?.jQuery && state.input.tagName === 'SELECT') window.django.jQuery(state.input).trigger('change.select2');
                state.filled = value;
                return true;
            } finally { applying = false; }
        }
        function apply(data, explicit, snapshot = null) {
            let preserved = false;
            states.forEach((state, key) => {
                if (explicit && snapshot && (state.revision !== snapshot.get(key)?.revision || state.input.value !== snapshot.get(key)?.value)) {
                    preserved = true;
                    return;
                }
                const suggestion = data.values?.[key];
                const hasValue = suggestion !== undefined && suggestion !== null && suggestion !== '';
                if (!hasValue) {
                    // A new person must not retain old automatically populated details.
                    if (explicit && state.filled !== null && !state.manual) setValue(state, '');
                    return;
                }
                const value = String(typeof suggestion === 'object' ? suggestion.value : suggestion);
                const expected = state.filled ?? state.initial;
                if (!explicit && (state.manual || state.input.value !== expected || (key === 'username' && state.input.value))) {
                    preserved ||= state.input.value !== value;
                    return;
                }
                if (setValue(state, suggestion) && explicit) state.manual = false;
            });
            reference.value = data.identity.reference;
            setStatus(explicit ? 'Persona seleccionada. Se actualizaron los campos disponibles asociados a la persona.' + (preserved ? ' Se conservaron las modificaciones realizadas durante la consulta.' : '') : 'Datos encontrados.' + (preserved ? ' Se conservaron los valores ingresados manualmente.' : ''));
            clearResults();
            if (explicit) query.focus();
        }
        function csrf() { return Array.from(form.elements).find(element => element.name === 'csrfmiddlewaretoken')?.value || ''; }
        async function post(url, payload, requestId) {
            const response = await fetch(url, {method: 'POST', credentials: 'same-origin', signal: controller.signal,
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf(), Accept: 'application/json'},
                body: JSON.stringify({context: container.dataset.context, object_id: container.dataset.objectId || '', ...payload})});
            if (requestId !== sequence) return null;
            if (!response.ok) throw new Error('Identity request failed');
            const data = await response.json();
            return requestId === sequence ? data : null;
        }
        async function select(candidate) {
            cancel();
            const requestId = sequence;
            controller = new AbortController();
            const snapshot = new Map(Array.from(states, ([key, state]) => [key, {revision: state.revision, value: state.input.value}]));
            setStatus('Consultando la persona seleccionada...');
            try {
                const data = await post(container.dataset.resolveUrl, {reference: candidate.reference}, requestId);
                if (data?.status === 'resolved') apply(data, true, snapshot);
                else if (data?.status === 'unassignable') setStatus(data.message || 'Esta persona no tiene una cuenta local asociable.');
            } catch (error) {
                if (error.name !== 'AbortError' && requestId === sequence) setStatus('No fue posible validar la selección. Busque nuevamente o continúe manualmente.');
            }
        }
        function showCandidates(candidates) {
            clearResults();
            candidates.forEach(candidate => {
                const button = document.createElement('button');
                button.type = 'button';
                button.textContent = [candidate.full_name, candidate.email, candidate.employee_number, candidate.source].filter(Boolean).join(' · ') || 'Seleccionar persona';
                button.addEventListener('click', () => select(candidate));
                results.appendChild(button);
            });
            results.hidden = !candidates.length;
            query.setAttribute('aria-expanded', String(!!candidates.length));
        }
        async function search(term = query.value, searchField = field.value) {
            cancel();
            clearResults();
            term = term.trim();
            if (term.length < 2 || term.length > 254) { setStatus('Escriba entre 2 y 254 caracteres para buscar.'); return; }
            const requestId = sequence;
            controller = new AbortController();
            setStatus('Buscando datos institucionales...');
            try {
                const data = await post(container.dataset.searchUrl, {q: term, field: searchField}, requestId);
                if (!data) return;
                if (data.status === 'resolved' && container.dataset.mode === 'add' && container.dataset.bound !== 'true' && container.dataset.explicitOnly !== 'true') {
                    apply(data, false);
                    return;
                }
                showCandidates(data.candidates || []);
                setStatus(data.incomplete ? 'La consulta está incompleta. No se completaron datos automáticamente; revise los candidatos o continúe manualmente.' : data.candidates?.length ? 'Seleccione una persona para completar o reemplazar sus datos.' : 'No se encontraron datos. Puede continuar manualmente.');
            } catch (error) {
                if (error.name !== 'AbortError' && requestId === sequence) setStatus('No fue posible consultar el directorio. Puede continuar manualmente.');
            }
        }
        function resetReference() {
            cancel();
            reference.value = '';
            clearResults();
            setStatus('');
        }
        function clearOwnedFields(exceptKey = null) {
            states.forEach((state, key) => {
                if (key !== exceptKey && state.filled !== null && !state.manual && state.input.value === state.filled) {
                    setValue(state, state.initial);
                    state.filled = null;
                }
            });
        }
        query.addEventListener('input', () => {
            resetReference();
            clearOwnedFields();
            timer = window.setTimeout(() => search(), 350);
        });
        field.addEventListener('change', resetReference);
        container.querySelector('[data-identity-search]')?.addEventListener('click', () => search());
        container.querySelector('[data-identity-clear]')?.addEventListener('click', () => {
            resetReference();
            if (container.dataset.clearFields === 'true') states.forEach(state => { setValue(state, ''); state.manual = false; state.filled = null; });
            setStatus('Selección quitada. Puede continuar con carga manual.');
        });
        query.setAttribute('aria-expanded', 'false');
        query.addEventListener('keydown', event => {
            if (event.key === 'Enter') { event.preventDefault(); search(); }
            if (event.key === 'ArrowDown') { const first = results.querySelector('button'); if (first) { event.preventDefault(); first.focus(); } }
            if (event.key === 'Escape') { event.preventDefault(); cancel(); clearResults(); }
        });
        results.addEventListener('keydown', event => {
            const buttons = Array.from(results.querySelectorAll('button'));
            const index = buttons.indexOf(event.target);
            if (event.key === 'Escape') { event.preventDefault(); clearResults(); query.focus(); }
            if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) && buttons.length) {
                event.preventDefault();
                const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
                buttons[next].focus();
            }
        });
        if (emailInput) {
            emailInput.addEventListener('input', () => {
                if (!applying) {
                    resetReference();
                    clearOwnedFields('email');
                }
            });
            emailInput.addEventListener('blur', () => {
                if (emailInput.value.trim() && emailInput.checkValidity()) search(emailInput.value, 'email');
            });
        }
    }
    function initialize(root = document) { root.querySelectorAll('[data-institutional-identity]').forEach(init); }
    window.NovaDeskIdentity = {initialize};
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => initialize());
    else initialize();
})();
