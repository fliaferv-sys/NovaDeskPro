(() => {
    'use strict';
    document.querySelectorAll('[data-technical-context]').forEach(panel => {
        if (window.matchMedia('(max-width: 768px)').matches) return;
        const status = panel.querySelector('[data-context-status]');
        const results = panel.querySelector('[data-context-results]');
        const query = panel.querySelector('[data-context-query]');
        const selection = panel.querySelector('[data-context-selection]');
        let revision = 0, controller;
        const labels = {full_name: 'Nombre', username: 'Usuario', email: 'Correo', phone: 'Teléfono',
            position: 'Cargo', department: 'Dependencia', location: 'Ubicación', employee_number: 'Legajo',
            employment_type: 'Vínculo', type: 'Tipo', name: 'Equipo', hostname: 'Hostname', ip: 'IP', mac: 'MAC', serial: 'Serie'};
        function node(tag, text, parent) {
            const element = document.createElement(tag);
            if (text) element.textContent = text;
            parent.appendChild(element); return element;
        }
        function section(parent, title, data, confidence) {
            const box = node('section', '', parent); box.className = 'ticket-form-card';
            node('h4', title, box);
            const list = node('dl', '', box); list.className = 'context-fields';
            Object.entries(data || {}).forEach(([key, value]) => {
                if (value && labels[key]) { node('dt', labels[key], list); node('dd', String(value), list); }
            });
            if (confidence) node('small', `Confianza: ${confidence}`, box);
            return box;
        }
        function choice(parent, title, candidates, describe) {
            const label = node('label', title, parent);
            const select = node('select', '', label); select.className = 'form-control';
            const empty = node('option', 'Sin selección', select); empty.value = '';
            candidates.forEach((candidate, index) => {
                const option = node('option', describe(candidate), select); option.value = String(index);
            });
            return select;
        }
        const personLabel = person => [person.data?.full_name, person.data?.email, (person.sources || []).join(' + ')].filter(Boolean).join(' · ');
        function invalidate() {
            revision++; controller?.abort(); selection.value = ''; results.replaceChildren();
            status.textContent = 'Consulte y revise el contexto antes de incluirlo.';
        }
        query.addEventListener('input', invalidate);
        panel.querySelector('[data-context-clear]').addEventListener('click', invalidate);
        async function load() {
            const current = ++revision;
            controller?.abort(); selection.value = ''; results.replaceChildren();
            const value = query.value.trim();
            if (!value) { status.textContent = 'Ingrese IP o hostname.'; return; }
            controller = new AbortController();
            const url = new URL(panel.dataset.url, window.location.origin);
            url.searchParams.set(/^\d+(\.\d+){3}$/.test(value) ? 'ip' : 'hostname', value);
            status.textContent = 'Consultando contexto…';
            try {
                const response = await fetch(url, {signal: controller.signal, credentials: 'same-origin', cache: 'no-store'});
                const context = await response.json();
                if (current !== revision) return;
                if (!response.ok) throw new Error('Consulta no disponible');
                section(results, 'Solicitante NovaDesk', context.requester);
                const requesterChoice = choice(results, 'Identidad institucional del solicitante', context.person?.candidates || [], personLabel);
                const requesterDetails = section(results, 'Identidad del solicitante', {});
                requesterChoice.addEventListener('change', () => {
                    selection.value = ''; requesterDetails.replaceChildren();
                    const person = context.person?.candidates?.[Number(requesterChoice.value)];
                    if (requesterChoice.value !== '' && person) section(requesterDetails, 'Datos institucionales', person.data, person.confidence);
                });
                (context.devices || []).forEach((device, index) => {
                    const article = node('article', '', results);
                    const box = section(article, 'Equipo detectado', {...device.data, ip: device.ip}, device.confidence);
                    const details = node('details', '', box); node('summary', 'Fuentes', details);
                    node('small', Object.values(device.provenance || {}).join(' · '), details);
                    const detected = device.detected_user?.candidates || [];
                    const detectedChoice = choice(article, 'Usuario detectado', detected, personLabel);
                    const detectedDetails = section(article, 'Usuario detectado', {});
                    detectedChoice.addEventListener('change', () => {
                        selection.value = ''; detectedDetails.replaceChildren();
                        const person = detected[Number(detectedChoice.value)];
                        if (detectedChoice.value !== '' && person) section(detectedDetails, 'Datos institucionales', person.data, person.confidence);
                    });
                    const assets = device.novadesk_assets || [];
                    const assetChoice = choice(article, 'Responsable NovaDesk / activo', assets,
                        asset => `${asset.code} · ${asset.responsible?.full_name || 'Sin responsable asignado'}`);
                    const ownerDetails = section(article, 'Responsable NovaDesk', {});
                    assetChoice.addEventListener('change', () => {
                        selection.value = ''; ownerDetails.replaceChildren();
                        const asset = assets[Number(assetChoice.value)];
                        if (assetChoice.value !== '' && asset) section(ownerDetails, 'Responsable registrado', asset.responsible);
                    });
                    requesterChoice.addEventListener('change', () => { selection.value = ''; });
                    const button = node('button', 'Seleccionar equipo e incluir contexto revisado', article);
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
                status.textContent = context.devices?.length > 1 ? 'Varios equipos: seleccione explícitamente el correcto.' :
                    context.devices?.length ? 'Equipo sugerido. Revise y seleccione para incluirlo.' : 'No identificado. Puede continuar sin contexto.';
            } catch (error) {
                if (error.name !== 'AbortError' && current === revision) status.textContent = 'Contexto no disponible. Puede continuar manualmente.';
            }
        }
        panel.querySelector('[data-context-load]').addEventListener('click', load);
    });
})();
