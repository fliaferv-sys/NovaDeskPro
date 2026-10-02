(() => {
    const initialized = new WeakSet();
    const sourceLabels = {
        RRHH: "RR.HH.",
        ACTIVE_DIRECTORY: "Active Directory",
        LOCAL: "NovaDesk",
    };

    function valueOrEmpty(value) {
        return value === null || value === undefined ? "" : String(value);
    }

    function initSelector(container) {
        if (initialized.has(container)) {
            return;
        }

        const searchInput = container.querySelector(
            ".institutional-recipient-search"
        );
        const results = container.querySelector(
            ".institutional-recipient-results"
        );
        const selectedSummary = container.querySelector(
            ".institutional-recipient-selected"
        );
        const status = container.querySelector(
            ".institutional-recipient-status"
        );
        const searchUrl = container.dataset.searchUrl;

        if (!searchInput || !results || !selectedSummary) {
            return;
        }

        initialized.add(container);
        results.hidden = true;
        results.setAttribute("role", "list");
        results.setAttribute("aria-live", "polite");
        searchInput.setAttribute("aria-autocomplete", "list");
        searchInput.setAttribute("aria-expanded", "false");

        const fieldNames = [
            "recipient_id_personal",
            "recipient_name",
            "recipient_email",
            "recipient_source",
            "recipient_employee_number",
            "recipient_position",
            "recipient",
        ];
        const form = container.closest("form");
        const fieldScope = form || container;
        const fields = {};
        fieldNames.forEach((name) => {
            fields[name] = fieldScope.querySelector(`[name="${name}"]`);
        });

        let debounceTimer = null;
        let activeController = null;
        let hasSelection = fieldNames.some((name) => {
            const field = fields[name];
            return field && Boolean(field.value);
        });
        let selectedSearchValue = fields.recipient_name
            ? fields.recipient_name.value
            : "";
        if (!selectedSearchValue && hasSelection) {
            selectedSearchValue = searchInput.value;
        }

        function setStatus(message) {
            if (!status) {
                return false;
            }
            status.textContent = message;
            status.hidden = !message;
            return true;
        }

        function clearResults() {
            results.replaceChildren();
            results.hidden = true;
            searchInput.setAttribute("aria-expanded", "false");
            setStatus("");
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

        function dispatchFieldEvents(field) {
            if (!field) {
                return;
            }
            field.dispatchEvent(new Event("input", { bubbles: true }));
            field.dispatchEvent(new Event("change", { bubbles: true }));
        }

        function setFieldValue(name, value) {
            const field = fields[name];
            if (!field) {
                return;
            }
            field.value = valueOrEmpty(value);
            dispatchFieldEvents(field);
        }

        function clearSelection() {
            fieldNames.forEach((name) => setFieldValue(name, ""));
            selectedSummary.replaceChildren();
            hasSelection = false;
            selectedSearchValue = "";
        }

        function sourceLabel(source) {
            return sourceLabels[source] || valueOrEmpty(source);
        }

        function appendSummaryLine(parent, className, text) {
            if (!text) {
                return;
            }
            const line = document.createElement("div");
            if (className) {
                line.className = className;
            }
            line.textContent = text;
            parent.appendChild(line);
        }

        function showSelectedEmployee(employee) {
            const name = valueOrEmpty(employee.name);
            const source = sourceLabel(employee.source);
            const email = valueOrEmpty(employee.email);
            const employeeNumber = valueOrEmpty(employee.employee_number);
            const position = valueOrEmpty(employee.position);

            setFieldValue("recipient_id_personal", employee.id_personal);
            setFieldValue("recipient_name", name);
            setFieldValue("recipient_email", email);
            setFieldValue("recipient_source", employee.source);
            setFieldValue("recipient_employee_number", employeeNumber);
            setFieldValue("recipient_position", position);
            setFieldValue("recipient", "");

            searchInput.value = name;
            selectedSearchValue = name;
            hasSelection = true;

            selectedSummary.replaceChildren();
            appendSummaryLine(
                selectedSummary,
                "institutional-recipient-selected-name",
                name
            );
            appendSummaryLine(
                selectedSummary,
                "institutional-recipient-selected-source",
                source
            );
            appendSummaryLine(
                selectedSummary,
                "institutional-recipient-selected-email",
                email
            );
            appendSummaryLine(
                selectedSummary,
                "institutional-recipient-selected-employee-number",
                employeeNumber
            );
            appendSummaryLine(
                selectedSummary,
                "institutional-recipient-selected-position",
                position
            );

            cancelPendingSearch();
            clearResults();
        }

        function appendOptionalDetail(parent, value) {
            if (!value) {
                return;
            }
            const detail = document.createElement("span");
            detail.textContent = value;
            parent.appendChild(detail);
        }

        function renderEmployee(employee) {
            const item = document.createElement("div");
            item.setAttribute("role", "listitem");

            const button = document.createElement("button");
            button.type = "button";
            button.className = "institutional-recipient-result";
            button.disabled = employee.is_active === false;

            const name = document.createElement("span");
            name.className = "institutional-recipient-result-name";
            name.textContent = valueOrEmpty(employee.name) || "—";
            button.appendChild(name);

            const details = document.createElement("span");
            details.className = "institutional-recipient-result-details";
            appendOptionalDetail(details, valueOrEmpty(employee.email));
            appendOptionalDetail(
                details,
                valueOrEmpty(employee.employee_number)
            );
            appendOptionalDetail(details, valueOrEmpty(employee.position));
            appendOptionalDetail(details, sourceLabel(employee.source));
            button.appendChild(details);

            if (employee.is_active === false) {
                const inactive = document.createElement("span");
                inactive.className = "institutional-recipient-result-inactive";
                inactive.textContent = "Inactivo";
                button.appendChild(inactive);
            } else {
                button.addEventListener("click", () => {
                    showSelectedEmployee(employee);
                });
            }

            item.appendChild(button);
            results.appendChild(item);
        }

        function showMessage(message) {
            results.replaceChildren();
            if (setStatus(message)) {
                results.hidden = true;
                searchInput.setAttribute("aria-expanded", "false");
                return;
            }

            const messageNode = document.createElement("p");
            messageNode.className = "institutional-recipient-message";
            messageNode.textContent = message;
            results.appendChild(messageNode);
            results.hidden = false;
            searchInput.setAttribute("aria-expanded", "true");
        }

        function showEmployees(employees) {
            results.replaceChildren();
            setStatus("");

            if (!employees.length) {
                showMessage("No se encontraron personas.");
                return;
            }

            employees.forEach(renderEmployee);
            results.hidden = false;
            searchInput.setAttribute("aria-expanded", "true");
        }

        async function searchEmployees(query) {
            if (!searchUrl) {
                showMessage("No fue posible consultar el Directorio Institucional.");
                return;
            }

            const controller = new AbortController();
            activeController = controller;
            showMessage("Buscando...");

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
                if (
                    activeController !== controller ||
                    searchInput.value.trim() !== query
                ) {
                    return;
                }
                if (!data || !Array.isArray(data.employees)) {
                    throw new Error("invalid_directory_response");
                }

                showEmployees(data.employees);
            } catch (error) {
                if (error.name === "AbortError") {
                    return;
                }
                if (activeController === controller) {
                    showMessage(
                        "No fue posible consultar el Directorio Institucional."
                    );
                }
            } finally {
                if (activeController === controller) {
                    activeController = null;
                }
            }
        }

        function scheduleSearch(rawQuery) {
            cancelPendingSearch();
            clearResults();
            const query = rawQuery.trim();
            if (query.length < 2) {
                return;
            }

            debounceTimer = window.setTimeout(() => {
                debounceTimer = null;
                searchEmployees(query);
            }, 300);
        }

        searchInput.addEventListener("input", () => {
            if (hasSelection && searchInput.value !== selectedSearchValue) {
                clearSelection();
            }
            scheduleSearch(searchInput.value);
        });

        searchInput.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                cancelPendingSearch();
                clearResults();
                event.preventDefault();
            }
        });
    }

    function initialize() {
        document.querySelectorAll(
            "[data-institutional-recipient-selector]"
        ).forEach(initSelector);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, { once: true });
    } else {
        initialize();
    }
})();
