/* ==========================================================
   SIDEBAR INTELIGENTE
   NOVADESK PRO — SPRINT 19.5
   ========================================================== */

   (function () {
    "use strict";

    const STORAGE_KEY = "novadesk_sidebar_collapsed";

    const initializeSidebar = function () {
        const body = document.body;

        const sidebar = document.getElementById(
            "appSidebar"
        );

        const toggleButton = document.getElementById(
            "sidebarToggleButton"
        );

        const toggleIcon = document.getElementById(
            "sidebarToggleIcon"
        );

        const mobileButton = document.getElementById(
            "mobileSidebarButton"
        );

        const overlay = document.getElementById(
            "sidebarOverlay"
        );

        const menuLinks = document.querySelectorAll(
            ".sidebar-menu-link"
        );

        if (!sidebar) {
            return;
        }

        const isMobile = function () {
            return window.matchMedia(
                "(max-width: 900px)"
            ).matches;
        };


        const updateToggleButton = function () {
            if (!toggleButton) {
                return;
            }

            const collapsed = body.classList.contains(
                "sidebar-collapsed"
            );

            toggleButton.setAttribute(
                "aria-expanded",
                collapsed ? "false" : "true"
            );

            toggleButton.setAttribute(
                "aria-label",
                collapsed
                    ? "Expandir menú"
                    : "Contraer menú"
            );

            toggleButton.setAttribute(
                "title",
                collapsed
                    ? "Expandir menú"
                    : "Contraer menú"
            );

            if (toggleIcon) {
                toggleIcon.className = collapsed
                    ? "bi bi-chevron-right"
                    : "bi bi-chevron-left";
            }
        };


        const saveSidebarPreference = function () {
            const collapsed = body.classList.contains(
                "sidebar-collapsed"
            );

            localStorage.setItem(
                STORAGE_KEY,
                collapsed ? "1" : "0"
            );
        };


        const loadSidebarPreference = function () {
            if (isMobile()) {
                body.classList.remove(
                    "sidebar-collapsed"
                );

                updateToggleButton();

                return;
            }

            const savedPreference = localStorage.getItem(
                STORAGE_KEY
            );

            if (savedPreference === "1") {
                body.classList.add(
                    "sidebar-collapsed"
                );
            } else {
                body.classList.remove(
                    "sidebar-collapsed"
                );
            }

            updateToggleButton();
        };


        const toggleDesktopSidebar = function () {
            if (isMobile()) {
                return;
            }

            body.classList.toggle(
                "sidebar-collapsed"
            );

            saveSidebarPreference();
            updateToggleButton();

            window.dispatchEvent(
                new Event("resize")
            );
        };


        const openMobileSidebar = function () {
            if (!isMobile()) {
                return;
            }

            body.classList.add(
                "sidebar-mobile-open"
            );

            if (mobileButton) {
                mobileButton.setAttribute(
                    "aria-expanded",
                    "true"
                );
            }
        };


        const closeMobileSidebar = function () {
            body.classList.remove(
                "sidebar-mobile-open"
            );

            if (mobileButton) {
                mobileButton.setAttribute(
                    "aria-expanded",
                    "false"
                );
            }
        };


        if (toggleButton) {
            toggleButton.addEventListener(
                "click",
                toggleDesktopSidebar
            );
        }


        if (mobileButton) {
            mobileButton.setAttribute(
                "aria-expanded",
                "false"
            );

            mobileButton.addEventListener(
                "click",
                function () {
                    const isOpen = body.classList.contains(
                        "sidebar-mobile-open"
                    );

                    if (isOpen) {
                        closeMobileSidebar();
                    } else {
                        openMobileSidebar();
                    }
                }
            );
        }


        if (overlay) {
            overlay.addEventListener(
                "click",
                closeMobileSidebar
            );
        }


        menuLinks.forEach(
            function (link) {
                link.addEventListener(
                    "click",
                    function () {
                        if (isMobile()) {
                            closeMobileSidebar();
                        }
                    }
                );
            }
        );


        document.addEventListener(
            "keydown",
            function (event) {
                if (event.key === "Escape") {
                    closeMobileSidebar();
                }
            }
        );


        window.addEventListener(
            "resize",
            function () {
                if (isMobile()) {
                    body.classList.remove(
                        "sidebar-collapsed"
                    );
                } else {
                    closeMobileSidebar();
                    loadSidebarPreference();
                }

                updateToggleButton();
            }
        );


        loadSidebarPreference();
    };


    if (document.readyState === "loading") {
        document.addEventListener(
            "DOMContentLoaded",
            initializeSidebar
        );
    } else {
        initializeSidebar();
    }
})();