(() => {
    "use strict";

    const MIN_QUERY_LENGTH = 2;
    const DEBOUNCE_DELAY = 300;
    const HIERARCHY_SEPARATOR = "\u203A";

    const SOURCE_LABELS = {
        RRHH: "RR.HH.",
        ACTIVE_DIRECTORY: "Active Directory",
        LOCAL: "NovaDesk",
    };

    const EMPTY_MESSAGE =
        "No se encontraron funcionarios que coincidan con la búsqueda.";
    const ERROR_MESSAGE =
        "No fue posible consultar el Directorio Institucional. Intente nuevamente.";

    function text(value) {
        return value === null || value === undefined ? "" : String(value);
    }

    function sourceLabel(source) {
        const key = text(source);
        return Object.prototype.hasOwnProperty.call(SOURCE_LABELS, key)
            ? SOURCE_LABELS[key]
            : key;
    }

    function element(tag, className) {
        const node = document.createElement(tag);
        if (className) {
            node.className = className;
        }
        return node;
    }

    function initials(employee) {
        const first = text(employee.first_name).trim();
        const last = text(employee.last_name).trim();
        if (first && last) {
            return (first.charAt(0) + last.charAt(0)).toUpperCase();
        }
        const name = text(employee.name).trim();
        return name ? name.charAt(0).toUpperCase() : "\u2014";
    }

    function badge(label, className) {
        const node = element("span", `dir-badge ${className}`);
        node.textContent = label;
        return node;
    }

    function definitionRow(term, value) {
        const item = element("div", "dir-row-cell");
        const dt = element("dt");
        dt.textContent = term;
        const dd = element("dd");
        dd.textContent = value;
        item.append(dt, dd);
        return item;
    }

    function buildOrganizationalRow(employee) {
        const unit = employee.organizational_unit;
        if (!unit || typeof unit !== "object") {
            return null;
        }
        const unitName = text(unit.name).trim();
        if (!unitName) {
            return null;
        }
        const row = element("div", "dir-row-org");
        const name = element("span", "dir-org-name");
        name.textContent = unitName;
        row.appendChild(name);
        const typeDisplay = text(unit.type_display).trim();
        if (typeDisplay) {
            const type = element("span", "dir-org-type");
            type.textContent = typeDisplay;
            row.appendChild(type);
        }
        return row;
    }

    function buildHierarchyRow(employee) {
        const path = employee.organizational_path;
        if (!Array.isArray(path) || path.length === 0) {
            return null;
        }
        const names = path
            .filter((unit) => unit && typeof unit === "object")
            .map((unit) => text(unit.name).trim())
            .filter((name) => name.length > 0);
        if (names.length === 0) {
            return null;
        }
        const row = element("div", "dir-row-org");
        const wrapper = element("span", "dir-hierarchy-path");
        names.forEach((name, index) => {
            if (index > 0) {
                const separator = element("span", "dir-sep");
                separator.textContent = HIERARCHY_SEPARATOR;
                wrapper.appendChild(separator);
            }
            const step = element("span", "dir-step");
            step.textContent = name;
            wrapper.appendChild(step);
        });
        row.appendChild(wrapper);
        return row;
    }

    function buildMetaList(employee) {
        const list = element("dl", "dir-row-meta");

        [
            ["Legajo", "employee_number"],
            ["Cargo", "position"],
            ["Ubicación", "location"],
            ["Teléfono", "phone"],
            ["Correo", "email"],
            ["Vínculo", "employment_type"],
        ].forEach(([label, field]) => {
            const value = text(employee[field]).trim();
            const item = definitionRow(label, value || "\u2014");
            if (field === "email" && value) {
                const link = element("a");
                link.href = `mailto:${value}`;
                link.textContent = value;
                item.querySelector("dd").replaceChildren(link);
            }
            list.appendChild(item);
        });
        const status = definitionRow("Estado", "\u2014");
        if (text(employee.status).trim()) {
            status.querySelector("dd").replaceChildren(badge(
                text(employee.status), employee.is_active === true ? "is-active" : "is-inactive"
            ));
        }
        const source = definitionRow("Fuente", "");
        source.querySelector("dd").appendChild(badge(sourceLabel(employee.source) || "\u2014", "is-source"));
        list.append(status, source);

        return list;
    }

    function buildEmployeeCard(employee) {
        const card = element("article", "dir-row");
        const personalId = text(employee.id_personal).trim();
        if (personalId) {
            card.setAttribute("data-personal-id", personalId);
        }

        const avatar = element("div", "dir-row-avatar");
        avatar.setAttribute("aria-hidden", "true");
        avatar.textContent = initials(employee);
        card.appendChild(avatar);

        const identity = element("div", "dir-row-identity");

        const name = element("div", "dir-row-name");
        name.textContent = text(employee.name).trim() || "\u2014";
        identity.appendChild(name);

        const organizationalRow = buildOrganizationalRow(employee);
        if (organizationalRow) {
            identity.appendChild(organizationalRow);
        }

        const hierarchyRow = buildHierarchyRow(employee);
        if (hierarchyRow) {
            identity.appendChild(hierarchyRow);
        }

        card.appendChild(identity);
        card.appendChild(buildMetaList(employee));

        return card;
    }
    function initDirectorySearch() {
        const container = document.querySelector("[data-directory-search]");
        if (!container) {
            return;
        }

        const input = document.querySelector("[data-directory-search-input]");
        const liveStatus = document.querySelector("[data-directory-live-status]");
        const serverResults = container.querySelector("[data-directory-server-results]");
        const liveResults = container.querySelector("[data-directory-live-results]");
        const searchUrl = container.getAttribute("data-directory-search-url");

        if (!input || !liveResults || !searchUrl) {
            return;
        }

        input.setAttribute("aria-autocomplete", "list");
        input.setAttribute("aria-controls", liveResults.id || "");
        input.setAttribute("aria-describedby", liveStatus ? liveStatus.id : "");

        let debounceTimer = null;
        let activeController = null;
        let lastQuery = "";

        function setStatus(message, tone) {
            if (!liveStatus) {
                return;
            }
            liveStatus.textContent = message || "";
            liveStatus.hidden = !message;
            liveStatus.setAttribute("data-tone", tone || "");
        }

        function clearLiveResults() {
            liveResults.replaceChildren();
            liveResults.hidden = true;
        }

        function showServerResults() {
            clearLiveResults();
            if (serverResults) {
                serverResults.hidden = false;
            }
            setStatus("", "");
        }

        function cancelPendingSearch() {
            if (debounceTimer !== null) {
                window.clearTimeout(debounceTimer);
                debounceTimer = null;
            }
            if (activeController) {
                activeController.abort();
                activeController = null;
            }
        }

        function showMessage(message, tone) {
            if (serverResults) {
                serverResults.hidden = true;
            }
            clearLiveResults();
            const paragraph = element(
                "p",
                tone === "error" ? "dir-empty is-error" : "dir-empty"
            );
            paragraph.textContent = message;
            liveResults.appendChild(paragraph);
            liveResults.hidden = false;
            setStatus("", "");
        }

        function showEmployees(employees) {
            if (serverResults) {
                serverResults.hidden = true;
            }
            clearLiveResults();

            const fragment = document.createDocumentFragment();
            employees.forEach((employee) => {
                if (employee && typeof employee === "object") {
                    fragment.appendChild(buildEmployeeCard(employee));
                }
            });
            liveResults.appendChild(fragment);
            liveResults.hidden = false;
            setStatus(
                employees.length === 1
                    ? "1 funcionario encontrado."
                    : `${employees.length} funcionarios encontrados.`,
                ""
            );
        }

        async function runSearch(query) {
            const controller = new AbortController();
            activeController = controller;
            setStatus("Buscando...", "loading");

            try {
                const url = new URL(searchUrl, window.location.href);
                url.searchParams.set("q", query);

                const response = await fetch(url.toString(), {
                    method: "GET",
                    headers: {
                        Accept: "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    credentials: "same-origin",
                    signal: controller.signal,
                });

                if (!response.ok) {
                    throw new Error("directory_search_failed");
                }

                const data = await response.json();

                if (activeController !== controller || input.value.trim() !== query) {
                    return;
                }

                if (!data || !Array.isArray(data.employees)) {
                    throw new Error("invalid_directory_response");
                }

                if (!data.employees.length) {
                    showMessage(EMPTY_MESSAGE, "empty");
                    return;
                }

                showEmployees(data.employees);
            } catch (error) {
                if (error && error.name === "AbortError") {
                    return;
                }
                if (activeController === controller) {
                    showMessage(ERROR_MESSAGE, "error");
                }
            } finally {
                if (activeController === controller) {
                    activeController = null;
                }
            }
        }

        function scheduleSearch() {
            cancelPendingSearch();

            const query = input.value.trim();
            lastQuery = query;

            if (query.length < MIN_QUERY_LENGTH) {
                if (container.getAttribute("data-directory-initial-query")) {
                    const url = new URL(window.location.href);
                    url.searchParams.delete("q");
                    window.location.assign(url.toString());
                    return;
                }
                showServerResults();
                return;
            }

            if (serverResults) {
                serverResults.hidden = true;
            }
            clearLiveResults();
            setStatus("", "");

            debounceTimer = window.setTimeout(() => {
                debounceTimer = null;
                runSearch(query);
            }, DEBOUNCE_DELAY);
        }

        input.addEventListener("input", scheduleSearch);

        input.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && input.value.trim() !== lastQuery) {
                cancelPendingSearch();
                showServerResults();
            }
        });

        showServerResults();
    }

    function initialize() {
        initDirectorySearch();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, { once: true });
    } else {
        initialize();
    }
})();