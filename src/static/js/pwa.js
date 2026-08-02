(function () {
    "use strict";

    let installPrompt = null;
    const installButton = document.getElementById("pwaInstallButton");

    if ("serviceWorker" in navigator) {
        window.addEventListener("load", function () {
            navigator.serviceWorker.register("/service-worker.js");
        });
    }

    window.addEventListener("beforeinstallprompt", function (event) {
        event.preventDefault();
        installPrompt = event;
        if (installButton) {
            installButton.hidden = false;
        }
    });

    if (installButton) {
        installButton.addEventListener("click", async function () {
            if (!installPrompt) {
                return;
            }
            installPrompt.prompt();
            await installPrompt.userChoice;
            installPrompt = null;
            installButton.hidden = true;
        });
    }

    window.addEventListener("appinstalled", function () {
        installPrompt = null;
        if (installButton) {
            installButton.hidden = true;
        }
    });
})();
