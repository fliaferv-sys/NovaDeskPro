/* ==========================================================
   MENÚ DESPLEGABLE DEL USUARIO
   NOVADESK PRO
   ========================================================== */

   (function () {
    "use strict";

    const initializeNavbarMenu = function () {
        const userButton = document.getElementById(
            "navbarUserButton"
        );

        const userDropdown = document.getElementById(
            "navbarUserDropdown"
        );

        if (!userButton || !userDropdown) {
            return;
        }

        const closeDropdown = function () {
            userDropdown.hidden = true;

            userButton.setAttribute(
                "aria-expanded",
                "false"
            );
        };

        const openDropdown = function () {
            userDropdown.hidden = false;

            userButton.setAttribute(
                "aria-expanded",
                "true"
            );
        };

        const toggleDropdown = function () {
            if (userDropdown.hidden) {
                openDropdown();
            } else {
                closeDropdown();
            }
        };

        userButton.addEventListener(
            "click",
            function (event) {
                event.preventDefault();
                event.stopPropagation();

                toggleDropdown();
            }
        );

        userDropdown.addEventListener(
            "click",
            function (event) {
                event.stopPropagation();
            }
        );

        document.addEventListener(
            "click",
            function () {
                closeDropdown();
            }
        );

        document.addEventListener(
            "keydown",
            function (event) {
                if (event.key === "Escape") {
                    closeDropdown();
                }
            }
        );
    };

    if (document.readyState === "loading") {
        document.addEventListener(
            "DOMContentLoaded",
            initializeNavbarMenu
        );
    } else {
        initializeNavbarMenu();
    }
})();