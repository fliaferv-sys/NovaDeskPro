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

    function caption(label) {
        const node = element("span", "dir-label");
        node.textContent = label;
        return node;
    }

    function badge(label, className) {
        const node = element("span", `dir-badge ${className}`);
        node.textContent = label;
        return node;
    }

    function definitionRow(term, value) {
        const item = element("div", "dir-meta-item");
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
        const row = element("p", "dir-org");
        row.appendChild(caption("Dependencia"));
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
        const row = element("p", "dir-hierarchy");
        row.appendChild(caption("Jerarquía"));
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
        const list = element("dl", "dir-meta");

        const employeeNumber = text(employee.employee_number).trim();
        if (employeeNumber) {
            list.appendChild(definitionRow("Legajo", employeeNumber));
        }

        const location = text(employee.location).trim();
        if (location) {
            list.appendChild(definitionRow("Ubicación", location));
        }

        const phone = text(employee.phone).trim();
        if (phone) {
            list.appendChild(definitionRow("Teléfono", phone));
        }

        const email = text(employee.email).trim();
        if (email) {
            const item = element("div", "dir-meta-item");
            const dt = element("dt");
            dt.textContent = "Correo";
            const dd = element("dd");
            const link = document.createElement("a");
            link.setAttribute("href", `mailto:${email}`);
            link.textContent = email;
            dd.appendChild(link);
            item.append(dt, dd);
            list.appendChild(item);
        }

        const employmentType = text(employee.employment_type).trim();
        if (employmentType) {
            list.appendChild(definitionRow("Vínculo", employmentType));
        }

        return list.childElementCount > 0 ? list : null;
    }

    function buildEmployeeCard(employee) {
        const card = element("article", "dir-person");
        const personalId = text(employee.id_personal).trim();
        if (personalId) {
            card.setAttribute("data-personal-id", personalId);
        }

        const main = element("div", "dir-person-main");

        const avatar = element("div", "dir-avatar");
        avatar.setAttribute("aria-hidden", "true");
        avatar.textContent = initials(employee);
        main.appendChild(avatar);

        const body = element("div", "dir-person-body");

        const head = element("div", "dir-person-head");
        const name = element("h2", "dir-person-name");
        name.textContent = text(employee.name).trim() || "\u2014";
        head.appendChild(name);

        const tags = element("div", "dir-tags");
        const status = text(employee.status).trim();
        if (status) {
            tags.appendChild(
                badge(
                    status,
                    employee.is_active === true ? "is-active" : "is-inactive"
                )
            );
        }
        const source = sourceLabel(employee.source).trim();
        if (source) {
            tags.appendChild(badge(source, "is-source"));
        }
        head.appendChild(tags);
        body.appendChild(head);

        const position = text(employee.position).trim();
        if (position) {
            const role = element("p", "dir-role");
            role.textContent = position;
            body.appendChild(role);
        }

        const organizationalRow = buildOrganizationalRow(employee);
        if (organizationalRow) {
            body.appendChild(organizationalRow);
        }

        const hierarchyRow = buildHierarchyRow(employee);
        if (hierarchyRow) {
            body.appendChild(hierarchyRow);
        }

        const meta = buildMetaList(employee);
        if (meta) {
            body.appendChild(meta);
        }

        main.appendChild(body);
        card.appendChild(main);
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
            setStatus(message, tone);
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