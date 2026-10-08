(() => {
    const modal = document.getElementById("photoPreviewModal");
    if (!modal) return;
    const image = modal.querySelector(".photo-preview-image");
    const close = modal.querySelector("[data-photo-preview-close]");
    let opener;
    let background = [];

    function hide() {
        if (modal.hidden) return;
        modal.hidden = true;
        modal.setAttribute("aria-hidden", "true");
        image.removeAttribute("src");
        document.body.classList.remove("photo-preview-open");
        background.forEach(([element, wasInert]) => { element.inert = wasInert; });
        background = [];
        if (opener?.isConnected) opener.focus();
    }

    function show(trigger) {
        if (!modal.hidden || !trigger.getAttribute("src")) return;
        opener = trigger;
        image.src = trigger.currentSrc || trigger.src;
        image.alt = trigger.alt || "Foto ampliada";
        // Move the dialog outside the page container before making it inert.
        document.body.appendChild(modal);
        background = Array.from(document.body.children)
            .filter(element => element !== modal)
            .map(element => [element, element.inert]);
        background.forEach(([element]) => { element.inert = true; });
        modal.hidden = false;
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("photo-preview-open");
        close.focus();
    }

    document.addEventListener("click", event => {
        const trigger = event.target.closest("[data-photo-preview]");
        if (trigger) { event.preventDefault(); show(trigger); }
        else if (event.target === modal || event.target.closest("[data-photo-preview-close]")) hide();
    });
    document.addEventListener("keydown", event => {
        if (!modal.hidden) {
            if (event.key === "Escape") { event.preventDefault(); hide(); }
            if (event.key === "Tab") { event.preventDefault(); close.focus(); }
        } else if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-photo-preview]")) {
            event.preventDefault();
            show(event.target);
        }
    });
})();
