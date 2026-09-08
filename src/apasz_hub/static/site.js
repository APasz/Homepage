const COPY_FEEDBACK_DURATION_MS = 1600;
const DRAFT_SYNC_DELAY_MS = 350;
const DRAFT_REVISION_HEADER = "X-Link-Card-Draft-Revision";
const CONFIG_CSRF_HEADER = "X-CSRF-Token";
const CONFIG_CSRF_FORM_NAME = "config-csrf-token";
const HEX_COLOUR_PATTERN = /^#[\da-f]{6}$/i;

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

function isHexColour(value) {
    return HEX_COLOUR_PATTERN.test(value);
}

function updateBrowserThemeColour(token, value) {
    const browserThemeColour = document.querySelector("meta[name='theme-color']");
    if (
        browserThemeColour instanceof HTMLMetaElement &&
        browserThemeColour.dataset.themeColorToken === token
    ) {
        browserThemeColour.content = value;
    }
}

function shadowCssValue(value) {
    const red = Number.parseInt(value.slice(1, 3), 16);
    const green = Number.parseInt(value.slice(3, 5), 16);
    const blue = Number.parseInt(value.slice(5, 7), 16);
    return `rgb(${red} ${green} ${blue} / var(--shadow-opacity))`;
}

function applyThemeColour(token, value) {
    document.documentElement.style.setProperty(`--color-${token}`, value);
    if (token === "shadow") {
        document.documentElement.style.setProperty("--shadow", shadowCssValue(value));
    }
    updateAutomaticLinkCardColours(token, value);
    updateBrowserThemeColour(token, value);
}

function updateAutomaticLinkCardColours(token, value) {
    for (const colourInput of document.querySelectorAll(
        "input[data-link-card-colour-fallback]",
    )) {
        if (
            !(colourInput instanceof HTMLInputElement) ||
            colourInput.dataset.linkCardColourFallback !== token
        ) {
            continue;
        }
        const control = colourInput.closest("[data-link-card-colour-control]");
        const autoInput = control?.querySelector(
            "input[data-link-card-colour-auto]",
        );
        if (autoInput instanceof HTMLInputElement && autoInput.checked) {
            colourInput.value = value;
        }
    }
}

function currentThemeColour(token) {
    const value = getComputedStyle(document.documentElement)
        .getPropertyValue(`--color-${token}`)
        .trim();
    return isHexColour(value) ? value : null;
}

function updateThemeColourValue(container, token, value) {
    for (const output of container.querySelectorAll("[data-theme-color-value]")) {
        if (
            output instanceof HTMLElement &&
            output.dataset.themeColorValue === token
        ) {
            output.textContent = value.toUpperCase();
        }
    }
}

function syncBrowserThemeColour() {
    const browserThemeColour = document.querySelector("meta[name='theme-color']");
    if (!(browserThemeColour instanceof HTMLMetaElement)) {
        return;
    }
    const token = browserThemeColour.dataset.themeColorToken;
    if (!token) {
        return;
    }
    const value = currentThemeColour(token);
    if (value !== null) {
        browserThemeColour.content = value;
    }
}

function configureThemeControls() {
    const form = document.querySelector("form[data-theme-controls]");
    if (!(form instanceof HTMLFormElement)) {
        return;
    }

    const inputs = [...form.querySelectorAll("input[data-theme-color]")].filter(
        (input) => input instanceof HTMLInputElement && input.type === "color",
    );
    const status = form.querySelector("[data-theme-status]");
    const resetButton = form.querySelector("button[data-theme-reset]");

    function report(message) {
        if (status instanceof HTMLElement) {
            status.textContent = message;
        }
    }

    function preview(input) {
        const token = input.dataset.themeColor;
        const value = input.value;
        if (!token || !isHexColour(value)) {
            return false;
        }
        applyThemeColour(token, value);
        updateThemeColourValue(form, token, value);
        return true;
    }

    function previewAndReport(input) {
        if (preview(input)) {
            report("Unsaved changes.");
        }
    }

    for (const input of inputs) {
        input.addEventListener("input", () => {
            previewAndReport(input);
        });
        input.addEventListener("change", () => {
            previewAndReport(input);
        });
    }

    if (!(resetButton instanceof HTMLButtonElement)) {
        return;
    }
    resetButton.addEventListener("click", () => {
        form.reset();
        for (const input of inputs) {
            preview(input);
        }
        report("Saved colours restored.");
    });
}

syncBrowserThemeColour();
configureThemeControls();

async function draftErrorMessage(response) {
    try {
        const payload = await response.json();
        if (typeof payload?.detail === "string") {
            return payload.detail;
        }
    } catch {
        // The endpoint may return a non-JSON server error.
    }
    return "Draft could not be updated.";
}

function configureLinkCardControls() {
    const form = document.querySelector("form[data-link-card-controls]");
    if (!(form instanceof HTMLFormElement)) {
        return;
    }

    const draftUrl = form.dataset.linkCardDraftUrl;
    if (!draftUrl) {
        return;
    }
    const csrfToken = form.querySelector(
        `input[name="${CONFIG_CSRF_FORM_NAME}"]`,
    );
    if (!(csrfToken instanceof HTMLInputElement) || !csrfToken.value) {
        return;
    }

    const status = form.querySelector("[data-link-card-status]");
    const controls = [
        ...form.querySelectorAll(
            "input[data-link-card-field], select[data-link-card-field], textarea[data-link-card-field]",
        ),
    ].filter(
        (control) =>
            control instanceof HTMLInputElement ||
            control instanceof HTMLSelectElement ||
            control instanceof HTMLTextAreaElement,
    );
    const deleteButtons = [
        ...form.querySelectorAll("button[data-link-card-delete]"),
    ].filter((button) => button instanceof HTMLButtonElement);
    let draftTimer = 0;
    let inputRevision = 0;
    let draftStoreRevision = Number.parseInt(
        form.dataset.linkCardDraftRevision ?? "",
        10,
    );
    let draftSyncing = false;

    function report(message) {
        if (status instanceof HTMLElement) {
            status.textContent = message;
        }
    }

    if (
        !Number.isSafeInteger(draftStoreRevision) ||
        draftStoreRevision < 0
    ) {
        report("Draft version is unavailable. Reload the configuration page.");
        return;
    }

    function updateCardSummary(control) {
        const field = control.dataset.linkCardField;
        if (!field) {
            return;
        }
        const card = control.closest("details[data-link-card-index]");
        const summary = card?.querySelector(
            `[data-link-card-summary="${field}"]`,
        );
        if (!(summary instanceof HTMLElement)) {
            return;
        }
        summary.textContent =
            field === "title" && !control.value ? "Untitled" : control.value;
    }

    function configureDestinationControls() {
        const schemaControls = [
            ...form.querySelectorAll("select[data-link-card-schema]"),
        ].filter((control) => control instanceof HTMLSelectElement);

        for (const schemaControl of schemaControls) {
            const card = schemaControl.closest("details[data-link-card-index]");
            if (!(card instanceof HTMLElement)) {
                continue;
            }
            const destinationControls = [
                ...card.querySelectorAll("[data-link-card-destination-schema]"),
            ].filter((control) => control instanceof HTMLElement);

            const selectDestinationControl = () => {
                for (const destinationControl of destinationControls) {
                    const isActive =
                        destinationControl.dataset.linkCardDestinationSchema ===
                        schemaControl.value;
                    destinationControl.hidden = !isActive;
                    const input = destinationControl.querySelector(
                        "input[data-link-card-field='destination']",
                    );
                    if (input instanceof HTMLInputElement) {
                        input.disabled = !isActive;
                    }
                }
            };

            selectDestinationControl();
            schemaControl.addEventListener("change", selectDestinationControl);
        }
    }

    function configureColourControls() {
        const colourInputs = [
            ...form.querySelectorAll("input[data-link-card-colour-fallback]"),
        ].filter((input) => input instanceof HTMLInputElement);

        for (const colourInput of colourInputs) {
            const control = colourInput.closest(
                "[data-link-card-colour-control]",
            );
            const autoInput = control?.querySelector(
                "input[data-link-card-colour-auto]",
            );
            if (!(autoInput instanceof HTMLInputElement)) {
                continue;
            }

            const useCustomColour = () => {
                autoInput.checked = false;
            };
            const useAutomaticColour = () => {
                if (!autoInput.checked) {
                    return;
                }
                const fallbackToken = colourInput.dataset.linkCardColourFallback;
                if (!fallbackToken) {
                    return;
                }
                const fallbackValue = currentThemeColour(fallbackToken);
                if (fallbackValue !== null) {
                    colourInput.value = fallbackValue;
                }
            };

            colourInput.addEventListener("input", useCustomColour);
            colourInput.addEventListener("change", useCustomColour);
            autoInput.addEventListener("change", useAutomaticColour);
        }
    }

    function scheduleDraftSync(delay = DRAFT_SYNC_DELAY_MS) {
        window.clearTimeout(draftTimer);
        draftTimer = window.setTimeout(() => {
            void syncDraft();
        }, delay);
    }

    async function syncDraft() {
        if (draftSyncing) {
            return;
        }
        if (!form.checkValidity()) {
            report("Complete the selected destination before saving.");
            return;
        }

        const requestRevision = inputRevision;
        draftSyncing = true;
        report("Updating draft…");
        try {
            const response = await fetch(draftUrl, {
                method: "POST",
                body: new FormData(form),
                headers: {
                    Accept: "application/json",
                    [CONFIG_CSRF_HEADER]: csrfToken.value,
                    [DRAFT_REVISION_HEADER]: String(draftStoreRevision),
                },
            });
            if (!response.ok) {
                throw new Error(await draftErrorMessage(response));
            }
            const nextStoreRevision = Number.parseInt(
                response.headers.get(DRAFT_REVISION_HEADER) ?? "",
                10,
            );
            if (!Number.isSafeInteger(nextStoreRevision) || nextStoreRevision < 0) {
                throw new Error("Draft update returned an invalid version.");
            }
            draftStoreRevision = nextStoreRevision;
            form.dataset.linkCardDraftRevision = String(nextStoreRevision);
            if (requestRevision === inputRevision) {
                report("Draft updated. Save Links to publish.");
            }
        } catch (error) {
            if (requestRevision === inputRevision) {
                report(
                    error instanceof Error
                        ? error.message
                        : "Draft could not be updated.",
                );
            }
        } finally {
            draftSyncing = false;
            if (requestRevision !== inputRevision) {
                scheduleDraftSync(0);
            }
        }
    }

    configureDestinationControls();
    configureColourControls();

    for (const deleteButton of deleteButtons) {
        deleteButton.addEventListener("click", (event) => {
            event.stopPropagation();
        });
    }

    for (const control of controls) {
        const updateDraft = () => {
            updateCardSummary(control);
            inputRevision += 1;
            report("Draft changes pending.");
            scheduleDraftSync();
        };
        control.addEventListener("input", updateDraft);
        control.addEventListener("change", updateDraft);
    }

    form.addEventListener("submit", (event) => {
        window.clearTimeout(draftTimer);
        const submitter = event.submitter;
        if (
            submitter instanceof HTMLButtonElement &&
            submitter.dataset.linkCardAdd !== undefined
        ) {
            report("Adding link…");
        } else if (
            submitter instanceof HTMLButtonElement &&
            submitter.dataset.linkCardDelete !== undefined
        ) {
            report("Deleting link…");
        } else {
            report("Saving link cards…");
        }
    });
}

function configureIconPicker() {
    const dialog = document.querySelector("dialog[data-icon-picker-dialog]");
    if (!(dialog instanceof HTMLDialogElement)) {
        return;
    }

    const triggers = [
        ...document.querySelectorAll("button[data-icon-picker-trigger]"),
    ].filter((trigger) => trigger instanceof HTMLButtonElement);
    const options = [
        ...dialog.querySelectorAll("button[data-icon-picker-option]"),
    ].filter((option) => option instanceof HTMLButtonElement);
    let activeInput = null;
    let activeTrigger = null;

    function inputForTrigger(trigger) {
        const control = trigger.closest(".link-card-control");
        const input = control?.querySelector(
            "input[data-link-card-field='icon']",
        );
        return input instanceof HTMLInputElement ? input : null;
    }

    function updateTrigger(trigger, iconPath) {
        const cardTitle = trigger.dataset.iconPickerCardTitle ?? "link card";
        trigger.textContent = iconPath;
        trigger.setAttribute(
            "aria-label",
            `Choose icon for ${cardTitle}. Current icon: ${iconPath}`,
        );
    }

    function selectOption(iconPath) {
        for (const option of options) {
            option.setAttribute(
                "aria-pressed",
                String(option.dataset.iconPickerOption === iconPath),
            );
        }
    }

    for (const trigger of triggers) {
        trigger.addEventListener("click", () => {
            const input = inputForTrigger(trigger);
            if (input === null || dialog.open) {
                return;
            }
            activeInput = input;
            activeTrigger = trigger;
            selectOption(input.value);
            dialog.showModal();
        });
    }

    for (const option of options) {
        option.addEventListener("click", () => {
            const iconPath = option.dataset.iconPickerOption;
            if (
                !iconPath ||
                !(activeInput instanceof HTMLInputElement) ||
                !(activeTrigger instanceof HTMLButtonElement)
            ) {
                return;
            }
            activeInput.value = iconPath;
            updateTrigger(activeTrigger, iconPath);
            selectOption(iconPath);
            activeInput.dispatchEvent(new Event("input", { bubbles: true }));
            dialog.close();
        });
    }

    dialog.addEventListener("click", (event) => {
        if (event.target === dialog) {
            dialog.close();
        }
    });
    dialog.addEventListener("close", () => {
        if (activeTrigger instanceof HTMLButtonElement) {
            activeTrigger.focus();
        }
        activeInput = null;
        activeTrigger = null;
    });
}

configureLinkCardControls();
configureIconPicker();
