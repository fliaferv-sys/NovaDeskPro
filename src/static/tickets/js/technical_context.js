(() => {
    'use strict';
    document.querySelectorAll('[data-technical-context]').forEach(panel => {
        if (panel.dataset.contextClient === 'true') {
            const selection = panel.querySelector('[data-context-selection]');
            fetch(panel.dataset.autoUrl, {credentials: 'same-origin', cache: 'no-store'}).then(response => {
                if (!response.ok) throw new Error('Unavailable');
                return response.json();
            }).then(context => {
                if (context.automatic_selection) {
                    selection.value = JSON.stringify({...context.automatic_selection, token: context.review_token});
                }
            }).catch(() => {});
            return;
        }
        const status = panel.querySelector('[data-context-status]');
        const results = panel.querySelector('[data-context-results]');
        const query = panel.querySelector('[data-context-query]');
        const selection = panel.querySelector('[data-context-selection]');
        const review = panel.querySelector('[data-context-review]');
        let renderPending;
        review?.addEventListener('toggle', () => {
            if (review.open && renderPending) { const render = renderPending; renderPending = null; render(); }
        });
        let revision = 0, controller;
        const labels = {full_name: 'Nombre', username: 'Usuario', email: 'Correo', phone: 'Teléfono',
            position: 'Cargo', department: 'Equipo de atención', organizational_unit: 'Dependencia institucional', branch: 'Sede o planta', location: 'Ubicación', employee_number: 'Legajo',
            employment_type: 'Vínculo', type: 'Tipo', name: 'Equipo', hostname: 'Hostname', ip: 'IP', mac: 'MAC', serial: 'Serie'};
        function node(tag, text, parent) {
            const element = document.createElement(tag);
            if (text) element.textContent = text;
            parent.appendChild(element); return element;
        }
        function section(parent, title, data, confidence) {
            const entries = Object.entries(data || {}).filter(([key, value]) => value && labels[key]);
            if (!entries.length) return null;
            const box = node('section', '', parent);
            node('h4', title, box);
            const list = node('dl', '', box); list.className = 'context-fields';
            Object.entries(data || {}).forEach(([key, value]) => {
                if (value && labels[key]) { node('dt', labels[key], list); node('dd', String(value), list); }
            });
            if (confidence) {
                const info = node('details', '', box); node('summary', 'Información técnica', info);
                node('small', `Confianza: ${confidence}`, info);
            }
            return box;
        }
        function choice(parent, title, candidates, describe) {
            if (!candidates.length) return {value: '', addEventListener() {}, dispatchEvent() {}};
            const label = node('label', title, parent);
            const select = node('select', '', label); select.className = 'form-control';
            const empty = node('option', 'Elegir u omitir', select); empty.value = '';
            candidates.forEach((candidate, index) => {
                const option = node('option', describe(candidate), select); option.value = String(index);
            });
            return select;
        }
        const personLabel = person => [person.data?.full_name, person.data?.email].filter(Boolean).join(' · ');
        function invalidate() {
            revision++; controller?.abort(); selection.value = 'skip'; results.replaceChildren();
            renderPending = null;
            status.textContent = 'Consulte y revise el contexto antes de incluirlo.';
        }
        query.addEventListener('input', invalidate);
        panel.querySelector('[data-context-clear]').addEventListener('click', invalidate);
        async function load(automatic = false) {
            automatic = automatic === true;
            const current = ++revision;
            controller?.abort(); selection.value = ''; results.replaceChildren();
            renderPending = null;
            const value = query.value.trim();
            if (!automatic && !value) { status.textContent = 'Ingrese IP o hostname.'; return; }
            controller = new AbortController();
            const url = new URL(automatic ? panel.dataset.autoUrl : panel.dataset.url, window.location.origin);
            if (!automatic) url.searchParams.set(/^\d+(\.\d+){3}$/.test(value) ? 'ip' : 'hostname', value);
            status.textContent = 'Consultando contexto…';
            try {
                const response = await fetch(url, {signal: controller.signal, credentials: 'same-origin', cache: 'no-store'});
                const context = await response.json();
                if (current !== revision) return;
                if (!response.ok) throw new Error('Consulta no disponible');
                const render = () => {
                const preparedSelection = selection.value;
                section(results, 'Solicitante', context.requester);
                const requesterChoice = choice(results, 'Identidad institucional del solicitante', context.person?.candidates || [], personLabel);
                const requesterDetails = node('div', '', results);
                requesterChoice.addEventListener('change', () => {
                    selection.value = ''; requesterDetails.replaceChildren();
                    const person = context.person?.candidates?.[Number(requesterChoice.value)];
                    if (requesterChoice.value !== '' && person) section(requesterDetails, 'Datos institucionales', person.data, person.confidence);
                });
                (context.devices || []).forEach((device, index) => {
                    const article = node('article', '', results);
                    const box = section(article, 'Equipo detectado', {...device.data, ip: device.ip}, device.confidence) || article;
                    const details = node('details', '', box); node('summary', 'Fuentes', details);
                    node('small', Object.values(device.provenance || {}).join(' · '), details);
                    const detected = device.detected_user?.candidates || [];
                    const detectedChoice = choice(article, 'Usuario detectado', detected, personLabel);
                    const detectedDetails = node('div', '', article);
                    detectedChoice.addEventListener('change', () => {
                        selection.value = ''; detectedDetails.replaceChildren();
                        const person = detected[Number(detectedChoice.value)];
                        if (detectedChoice.value !== '' && person) section(detectedDetails, 'Datos institucionales', person.data, person.confidence);
                    });
                    const assets = device.novadesk_assets || [];
                    const assetChoice = choice(article, 'Responsable NovaDesk / activo', assets,
                        asset => `${asset.code} · ${asset.responsible?.full_name || 'Sin responsable asignado'}`);
                    const ownerDetails = node('div', '', article);
                    assetChoice.addEventListener('change', () => {
                        selection.value = ''; ownerDetails.replaceChildren();
                        const asset = assets[Number(assetChoice.value)];
                        if (assetChoice.value !== '' && asset) section(ownerDetails, 'Responsable registrado', asset.responsible);
                    });
                    requesterChoice.addEventListener('change', () => { selection.value = ''; });
                    if (automatic && context.automatic_selection?.device === index) {
                        const approved = context.automatic_selection;
                        [[requesterChoice, approved.requester], [detectedChoice, approved.detected], [assetChoice, approved.asset]].forEach(([select, number]) => {
                            if (number !== null && number !== undefined) {
                                select.value = String(number);
                                select.dispatchEvent(new Event('change', {bubbles: true}));
                            }
                        });
                    }
                    const button = node('button', 'Seleccionar equipo', article);
                    button.type = 'button'; button.className = 'btn btn-outline';
                    button.addEventListener('click', () => {
                        if (current !== revision) return;
                        const number = select => select.value === '' ? null : Number(select.value);
                        selection.value = JSON.stringify({token: context.review_token, device: index,
                            requester: number(requesterChoice), detected: number(detectedChoice), asset: number(assetChoice)});
                        status.textContent = `Contexto revisado: ${device.data?.name || device.data?.hostname || 'equipo seleccionado'}. Se validará al crear el ticket.`;
                    });
                });
                (context.warnings || []).forEach(warning => node('p', warning, results));
                selection.value = preparedSelection;
                };
                if (!automatic || !review || review.open) {
                    if (review && !automatic) review.open = true;
                    render();
                } else renderPending = render;
                if (automatic && context.automatic_selection) {
                    selection.value = JSON.stringify({...context.automatic_selection, token: context.review_token});
                    status.textContent = '✓ Contexto técnico detectado automáticamente';
                } else status.textContent = context.devices?.length > 1 ? `Se encontraron ${context.devices.length} equipos relacionados. Revisar selección.` :
                    context.devices?.length ? 'Un equipo relacionado. Revisar selección.' : 'No se encontró un equipo relacionado automáticamente.';
            } catch (error) {
                if (error.name !== 'AbortError' && current === revision) status.textContent = 'Contexto no disponible. Puede continuar manualmente.';
            }
        }
        panel.querySelector('[data-context-load]').addEventListener('click', load);
        if (panel.dataset.autoUrl) load(true);
    });
})();
