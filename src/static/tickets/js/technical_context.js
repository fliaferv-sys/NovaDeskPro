(() => {
    'use strict';
    document.querySelectorAll('[data-technical-context]').forEach(panel => {
        if (window.matchMedia('(max-width: 768px)').matches) return;
        const status = panel.querySelector('[data-context-status]');
        const results = panel.querySelector('[data-context-results]');
        let revision = 0;
        let controller;
        const line = (parent, text) => {
            const p = document.createElement('p'); p.textContent = text; parent.appendChild(p);
        };
        const labels = {full_name: 'Nombre completo', username: 'Usuario', email: 'Correo', phone: 'Teléfono',
            position: 'Cargo', department: 'Dependencia', location: 'Ubicación', type: 'Tipo', name: 'Nombre del equipo',
            hostname: 'Hostname', mac: 'MAC', serial: 'Serie', contact: 'Contacto GLPI', glpi_user: 'Usuario GLPI', last_modified: 'Última modificación'};
        const describe = person => Object.entries(person.data || {}).filter(([, value]) => value)
            .map(([key, value]) => `${labels[key] || key}: ${value} (${person.provenance?.[key] || 'NovaDesk'})`).join('\n');
        const snapshotButton = (parent, text) => {
            const button = document.createElement('button'); button.type = 'button';
            button.className = 'btn btn-outline'; button.textContent = 'Añadir contexto revisado a descripción';
            button.addEventListener('click', () => {
                const description = panel.closest('form')?.querySelector('[name="description"]');
                if (description) {
                    const block = `[[NOVADESK_TECHNICAL_CONTEXT_V1]]\n${text}\n[[/NOVADESK_TECHNICAL_CONTEXT_V1]]`;
                    if (!description.value.includes(block)) description.value += `${description.value ? '\n\n' : ''}${block}`;
                    description.dispatchEvent(new Event('input', {bubbles: true}));
                    status.textContent = 'Contexto añadido. Revise la descripción antes de crear el ticket.';
                }
            }); parent.appendChild(button);
        };
        async function load() {
            const current = ++revision;
            controller?.abort(); controller = new AbortController();
            const query = panel.querySelector('[data-context-query]').value.trim();
            const url = new URL(panel.dataset.url, window.location.origin);
            if (query) url.searchParams.set(/^\d+(\.\d+){3}$/.test(query) ? 'ip' : 'hostname', query);
            status.textContent = 'Consultando contexto…'; results.replaceChildren();
            try {
                const response = await fetch(url, {signal: controller.signal, credentials: 'same-origin', cache: 'no-store'});
                const data = await response.json();
                if (current !== revision) return;
                if (!response.ok) throw new Error('Consulta no disponible.');
                const requester = data.requester || {};
                line(results, `Solicitante NovaDesk: ${requester.full_name || 'No disponible'} · ${requester.email || ''}`);
                (data.person?.candidates || []).forEach(person => {
                    const text = `Identidad consultada (${person.confidence}):\n${describe(person)}`;
                    line(results, text); snapshotButton(results, `Solicitante: ${requester.full_name || ''}\n${text}`);
                });
                (data.devices || []).forEach(device => {
                    const article = document.createElement('article'); results.appendChild(article);
                    const text = `Equipo detectado (${device.confidence}):\n${describe(device)}\nIP: ${device.ip || 'No disponible'} (${device.provenance?.ip || 'Sin fuente de red'})`;
                    line(article, text);
                    const detected = device.detected_user?.candidates || [];
                    detected.forEach(person => line(article, `Usuario detectado (${person.confidence}): ${describe(person)}`));
                    const owners = [];
                    (device.novadesk_assets || []).forEach(asset => {
                        const owner = asset.responsible?.full_name || 'Sin responsable asignado';
                        owners.push(`Responsable NovaDesk (${asset.code}): ${owner}`);
                        line(article, owners[owners.length - 1]);
                        if (asset.can_select && device.novadesk_assets.length === 1) {
                            const select = panel.closest('form')?.querySelector('[name="asset"]');
                            if (select && Array.from(select.options).some(option => option.value === asset.id)) {
                                const button = document.createElement('button'); button.type = 'button'; button.className = 'btn btn-outline';
                                button.textContent = `Seleccionar equipo ${asset.code}`;
                                button.addEventListener('click', () => { select.value = asset.id; select.dispatchEvent(new Event('change', {bubbles: true})); });
                                article.appendChild(button);
                            }
                        }
                    });
                    snapshotButton(article, `Solicitante: ${requester.full_name || ''}\n${text}\n${detected.map(person => `Usuario detectado (${person.confidence}): ${describe(person)}`).join('\n')}\n${owners.join('\n')}`);
                });
                (data.warnings || []).forEach(warning => line(results, warning));
                status.textContent = data.devices?.length > 1 ? 'Varios equipos: revise cada candidato.' : 'Datos disponibles para revisión; no se asociaron automáticamente.';
            } catch (error) {
                if (error.name !== 'AbortError' && current === revision) status.textContent = 'Contexto no disponible. Puede continuar manualmente.';
            }
        }
        panel.querySelector('[data-context-load]').addEventListener('click', load);
        load();
    });
})();
