const COPY_FEEDBACK_DURATION_MS = 1600;

async function copyText(text) {
    if (navigator.clipboard?.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return;
        } catch {
            // Some browsers expose the API but deny a write; try the legacy path below.
        }
    }

    copyWithLegacyCommand(text);
}

function copyWithLegacyCommand(text) {
    const temporaryInput = document.createElement("textarea");
    temporaryInput.value = text;
    temporaryInput.setAttribute("readonly", "");
    temporaryInput.style.position = "fixed";
    temporaryInput.style.opacity = "0";
    document.body.append(temporaryInput);
    try {
        temporaryInput.select();
        if (!document.execCommand("copy")) {
            throw new Error("Clipboard copying is unavailable.");
        }
    } finally {
        temporaryInput.remove();
    }
}

function copyAndReport(text, status, restoreStatus) {
    return copyText(text)
        .then(() => {
            status.textContent = "Copied";
        })
        .catch(() => {
            status.textContent = "Copy unavailable";
        })
        .finally(restoreStatus);
}

function canDelayCurrentTabNavigation(event, link) {
    const target = link.target.toLowerCase();
    const isHttpNavigation = link.protocol === "http:" || link.protocol === "https:";
    return (
        !event.defaultPrevented &&
        event.button === 0 &&
        !event.metaKey &&
        !event.ctrlKey &&
        !event.shiftKey &&
        !event.altKey &&
        (target === "" || target === "_self") &&
        isHttpNavigation
    );
}

for (const link of document.querySelectorAll("a[data-copy-text]")) {
    const copyTextValue = link.dataset.copyText;
    const status = link.querySelector("[data-copy-status]");
    if (!copyTextValue || !(status instanceof HTMLElement)) {
        continue;
    }

    const originalStatus = status.textContent;
    let restoreTimer;
    function restoreStatus() {
        window.clearTimeout(restoreTimer);
        restoreTimer = window.setTimeout(() => {
            status.textContent = originalStatus;
        }, COPY_FEEDBACK_DURATION_MS);
    }
    link.addEventListener("click", (event) => {
        const copy = copyAndReport(copyTextValue, status, restoreStatus);
        if (!canDelayCurrentTabNavigation(event, link)) {
            void copy;
            return;
        }

        event.preventDefault();
        void copy.then(() => {
            window.location.assign(link.href);
        });
    });
}
