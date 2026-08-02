(function () {
    "use strict";

    const chatContainer = document.getElementById("chatContainer");
    const messageInput = document.querySelector("#commentForm textarea");
    const commentForm = document.getElementById("commentForm");
    const messageCount = document.querySelector(".chat-count");

    if (!chatContainer || !chatContainer.dataset.liveUrl) {
        return;
    }

    const draftKey = "novadesk_ticket_draft_" + window.location.pathname;
    const submittedKey = draftKey + "_submitted";
    let currentRevision = chatContainer.dataset.revision || "";
    let checking = false;
    let sending = false;

    const applyConversationHtml = function (html) {
        const incomingDocument = new DOMParser().parseFromString(
            html,
            "text/html"
        );
        const incomingChat = incomingDocument.getElementById("chatContainer");
        const incomingCount = incomingDocument.querySelector(".chat-count");

        if (!incomingChat) {
            return false;
        }

        const newRevision = incomingChat.dataset.revision || "";
        const changed = newRevision && newRevision !== currentRevision;

        if (changed) {
            chatContainer.innerHTML = incomingChat.innerHTML;
            chatContainer.scrollTop = chatContainer.scrollHeight;
            currentRevision = newRevision;
            chatContainer.dataset.revision = newRevision;
            if (messageCount && incomingCount) {
                messageCount.textContent = incomingCount.textContent;
            }
        }

        return changed;
    };

    const fetchConversationHtml = async function () {
        const response = await fetch(window.location.pathname, {
            cache: "no-store",
            credentials: "same-origin",
            headers: { "X-Requested-With": "XMLHttpRequest" }
        });
        if (!response.ok || response.redirected) {
            return false;
        }
        return applyConversationHtml(await response.text());
    };

    if (messageInput) {
        const wasSubmitted = sessionStorage.getItem(submittedKey) === "1";
        if (wasSubmitted) {
            sessionStorage.removeItem(draftKey);
            sessionStorage.removeItem(submittedKey);
        }
        const savedDraft = sessionStorage.getItem(draftKey);
        if (!wasSubmitted && savedDraft && !messageInput.value) {
            messageInput.value = savedDraft;
            messageInput.dispatchEvent(new Event("input", { bubbles: true }));
        }

        messageInput.addEventListener("input", function () {
            if (messageInput.value) {
                sessionStorage.setItem(draftKey, messageInput.value);
            } else {
                sessionStorage.removeItem(draftKey);
            }
        });

    }

    // El envío se deja a cargo del formulario nativo de Django.
    if (false && commentForm && messageInput) {
        commentForm.addEventListener("submit", async function (event) {
            event.preventDefault();
            if (sending) {
                return;
            }

            const message = messageInput.value.trim();
            const selectedFile = commentForm.querySelector(
                "input[type='file']"
            );
            const hasFile = selectedFile && selectedFile.files.length > 0;
            if (!message && !hasFile) {
                return;
            }

            if (navigator.maxTouchPoints > 0) {
                messageInput.focus({ preventScroll: true });
            }

            sending = true;
            const pageScrollPosition = window.scrollY;
            const submitButton = commentForm.querySelector(
                "button[type='submit']"
            );
            if (submitButton) submitButton.disabled = true;

            try {
                const response = await fetch(commentForm.action || window.location.href, {
                    method: "POST",
                    body: new FormData(commentForm),
                    credentials: "same-origin",
                    cache: "no-store",
                    headers: { "X-Requested-With": "XMLHttpRequest" }
                });

                if (!response.ok) {
                    let errorMessage = "No fue posible enviar el mensaje.";
                    try {
                        const errorData = await response.json();
                        if (errorData.errors && errorData.errors.length) {
                            errorMessage = errorData.errors.join(" ");
                        }
                    } catch (parseError) {
                        // Se conserva el mensaje general.
                    }
                    throw new Error(errorMessage);
                }

                const result = await response.json();
                if (!result.success) {
                    throw new Error("El servidor no confirmó el mensaje.");
                }

                await fetchConversationHtml();

                // Un sondeo paralelo puede haber actualizado el chat primero.
                // Una respuesta HTTP correcta confirma igualmente el guardado.
                messageInput.value = "";
                const fileInput = commentForm.querySelector(
                    "input[type='file']"
                );
                const filePreview = document.getElementById("filePreview");
                if (fileInput) fileInput.value = "";
                if (filePreview) filePreview.style.display = "none";
                messageInput.dispatchEvent(
                    new Event("input", { bubbles: true })
                );
                sessionStorage.removeItem(draftKey);
                sessionStorage.removeItem(submittedKey);

                window.scrollTo(0, pageScrollPosition);
                window.requestAnimationFrame(function () {
                    window.scrollTo(0, pageScrollPosition);
                    window.requestAnimationFrame(function () {
                        window.scrollTo(0, pageScrollPosition);
                    });
                });
            } catch (error) {
                window.alert(
                    error.message
                    || "No se pudo enviar el mensaje. Revise la conexión."
                );
            } finally {
                sending = false;
                if (submitButton) submitButton.disabled = false;
            }
        });
    }

    if (commentForm) {
        commentForm.addEventListener("submit", function () {
            sessionStorage.removeItem(draftKey);
            sessionStorage.removeItem(submittedKey);
        });
    }

    const checkConversation = async function () {
        if (checking || document.hidden) {
            return;
        }
        checking = true;

        try {
            const response = await fetch(chatContainer.dataset.liveUrl, {
                cache: "no-store",
                credentials: "same-origin",
                headers: { "X-Requested-With": "XMLHttpRequest" }
            });
            if (!response.ok || response.redirected) {
                return;
            }

            const data = await response.json();
            if (data.revision && data.revision !== currentRevision) {
                await fetchConversationHtml();
            }
        } catch (error) {
            // Se reintenta automáticamente en el siguiente intervalo.
        } finally {
            checking = false;
        }
    };

    window.setInterval(checkConversation, 3000);
    document.addEventListener("visibilitychange", function () {
        if (!document.hidden) {
            checkConversation();
        }
    });
})();
