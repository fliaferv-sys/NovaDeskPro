document.addEventListener("DOMContentLoaded", function () {

    // ======================================================
    // MOSTRAR / OCULTAR CONTRASEÑA
    // ======================================================

    const passwordInput = document.querySelector('input[name="password"]');
    const toggleButton = document.querySelector(".password-toggle");

    if (passwordInput && toggleButton) {
        toggleButton.addEventListener("click", function () {
            if (passwordInput.type === "password") {
                passwordInput.type = "text";
                toggleButton.textContent = "🙈";
            } else {
                passwordInput.type = "password";
                toggleButton.textContent = "👁";
            }
        });
    }


    // ======================================================
    // VISTA PREVIA DE ARCHIVOS ADJUNTOS
    // SPRINT 11.5
    // ======================================================

    const fileInput = document.querySelector(
        'input[type="file"][name="file"]'
    );

    const dropZone = document.getElementById(
        "attachment-drop-zone"
    );

    const previewContainer = document.querySelector(
        "#attachment-preview-container"
    );

    const previewImage = document.querySelector(
        "#attachment-preview-image"
    );

    const previewIcon = document.querySelector(
        "#attachment-preview-icon"
    );

    const previewName = document.querySelector(
        "#attachment-preview-name"
    );

    const previewSize = document.querySelector(
        "#attachment-preview-size"
    );

    const removeButton = document.querySelector(
        "#attachment-preview-remove"
    );

    if (
        fileInput &&
        dropZone &&
        previewContainer &&
        previewImage &&
        previewIcon &&
        previewName &&
        previewSize &&
        removeButton
    ) {

        ["dragenter", "dragover"].forEach(function (eventName) {
            dropZone.addEventListener(eventName, function (event) {
                event.preventDefault();
                event.stopPropagation();
        
                dropZone.classList.add("is-dragging");
            });
        });
        
        ["dragleave", "drop"].forEach(function (eventName) {
            dropZone.addEventListener(eventName, function (event) {
                event.preventDefault();
                event.stopPropagation();
        
                dropZone.classList.remove("is-dragging");
            });
        });
        
        dropZone.addEventListener("drop", function (event) {
            const droppedFiles = event.dataTransfer.files;
        
            if (!droppedFiles.length) {
                return;
            }
        
            const dataTransfer = new DataTransfer();
            dataTransfer.items.add(droppedFiles[0]);
        
            fileInput.files = dataTransfer.files;
            fileInput.dispatchEvent(new Event("change"));
        });

        fileInput.addEventListener("change", function () {
            const file = fileInput.files[0];

            if (!file) {
                resetAttachmentPreview();
                return;
            }

            previewContainer.hidden = false;
            previewName.textContent = file.name;
            previewSize.textContent = formatFileSize(file.size);

            const extension = getFileExtension(file.name);
            const isImage = file.type.startsWith("image/");

            if (isImage) {
                const imageUrl = URL.createObjectURL(file);

                previewImage.src = imageUrl;
                previewImage.hidden = false;
                previewIcon.hidden = true;
            } else {
                previewImage.src = "";
                previewImage.hidden = true;

                previewIcon.textContent = getFileIcon(extension);
                previewIcon.hidden = false;
            }
        });

        removeButton.addEventListener("click", function () {
            fileInput.value = "";
            resetAttachmentPreview();
        });
    }


    function resetAttachmentPreview() {
        if (!previewContainer) {
            return;
        }

        previewContainer.hidden = true;

        if (previewImage) {
            previewImage.src = "";
            previewImage.hidden = true;
        }

        if (previewIcon) {
            previewIcon.textContent = "📁";
            previewIcon.hidden = false;
        }

        if (previewName) {
            previewName.textContent = "";
        }

        if (previewSize) {
            previewSize.textContent = "";
        }
    }


    function getFileExtension(filename) {
        const parts = filename.toLowerCase().split(".");

        if (parts.length < 2) {
            return "";
        }

        return parts.pop();
    }


    function getFileIcon(extension) {
        const iconMap = {
            pdf: "📄",
            doc: "📝",
            docx: "📝",
            xls: "📊",
            xlsx: "📊",
            txt: "📃",
            zip: "📦",
        };

        return iconMap[extension] || "📁";
    }


    function formatFileSize(sizeInBytes) {
        if (sizeInBytes < 1024) {
            return `${sizeInBytes} bytes`;
        }

        const sizeInKB = sizeInBytes / 1024;

        if (sizeInKB < 1024) {
            return `${sizeInKB.toFixed(1)} KB`;
        }

        const sizeInMB = sizeInKB / 1024;

        return `${sizeInMB.toFixed(1)} MB`;
    }
});

/* ==========================================================
   MENÚ DE USUARIO DEL NAVBAR
   ========================================================== */

   document.addEventListener("DOMContentLoaded", function () {

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

    userButton.addEventListener(
        "click",
        function (event) {
            event.stopPropagation();

            if (userDropdown.hidden) {
                openDropdown();
            } else {
                closeDropdown();
            }
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
        closeDropdown
    );

    document.addEventListener(
        "keydown",
        function (event) {
            if (event.key === "Escape") {
                closeDropdown();
            }
        }
    );

});