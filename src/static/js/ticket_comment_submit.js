(function () {
    "use strict";

    const form = document.getElementById("commentForm");
    const input = document.querySelector("#commentForm textarea");
    const button = document.querySelector("#commentForm button[type='submit']");
    const chat = document.getElementById("chatContainer");
    const count = document.querySelector(".chat-count");

    if (!form || !input || !button || !chat) return;

    let sending = false;

    const refreshChat = async function () {
        const response = await fetch(window.location.pathname, {
            cache: "no-store",
            credentials: "same-origin",
            headers: { "X-Requested-With": "XMLHttpRequest" }
        });
        if (!response.ok) return;

        const documentCopy = new DOMParser().parseFromString(
            await response.text(),
            "text/html"
        );
        const newChat = documentCopy.getElementById("chatContainer");
        const newCount = documentCopy.querySelector(".chat-count");

        if (newChat) {
            chat.innerHTML = newChat.innerHTML;
            chat.dataset.revision = newChat.dataset.revision || "";
            chat.scrollTop = chat.scrollHeight;
        }
        if (count && newCount) count.textContent = newCount.textContent;
    };

    const sendComment = async function () {
        if (sending) return;

        const fileInput = form.querySelector("input[type='file']");
        const hasFile = fileInput && fileInput.files.length > 0;
        if (!input.value.trim() && !hasFile) return;

        sending = true;
        const scrollPosition = window.scrollY;
        button.disabled = true;

        // Se devuelve el foco durante el gesto del usuario, antes del fetch.
        input.focus({ preventScroll: true });

        try {
            const response = await fetch(window.location.pathname, {
                method: "POST",
                body: new FormData(form),
                cache: "no-store",
                credentials: "same-origin",
                headers: { "X-Requested-With": "XMLHttpRequest" }
            });
            const result = await response.json();
            if (!response.ok || !result.success) {
                throw new Error(
                    (result.errors && result.errors.join(" "))
                    || "No fue posible enviar el mensaje."
                );
            }

            input.value = "";
            if (fileInput) fileInput.value = "";
            const preview = document.getElementById("filePreview");
            if (preview) preview.style.display = "none";
            input.dispatchEvent(new Event("input", { bubbles: true }));
            sessionStorage.removeItem(
                "novadesk_ticket_draft_" + window.location.pathname
            );

            await refreshChat();
            window.scrollTo(0, scrollPosition);
            input.focus({ preventScroll: true });
        } catch (error) {
            window.alert(error.message || "No fue posible enviar el mensaje.");
        } finally {
            sending = false;
            button.disabled = false;
        }
    };

    // Evita que el botón quite el foco al apoyar el dedo o el mouse.
    button.addEventListener("pointerdown", function (event) {
        event.preventDefault();
    });

    button.addEventListener("pointerup", function (event) {
        event.preventDefault();
        sendComment();
    });

    button.addEventListener("click", function (event) {
        event.preventDefault();
        sendComment();
    });

    form.addEventListener("submit", function (event) {
        event.preventDefault();
        sendComment();
    });
})();
