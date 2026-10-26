document.addEventListener("DOMContentLoaded", () => {
    const panel = document.querySelector("[data-moderation-url]");
    if (!panel) return;

    const form = panel.closest("form");
    const title = form.querySelector("#id_title");
    const description = form.querySelector("#id_description");
    const result = panel.querySelector("#moderation-result");
    const csrfToken = form.querySelector("[name=csrfmiddlewaretoken]").value;
    let requestNumber = 0;

    async function checkContent() {
        const currentRequest = ++requestNumber;
        const text = `${title.value}\n${description.value}`.trim();
        if (!text) {
            result.textContent = "";
            return;
        }

        result.replaceChildren();
        const spinner = document.createElement("span");
        spinner.className = "moderation-spinner";
        spinner.setAttribute("aria-hidden", "true");
        const loading = document.createElement("span");
        loading.textContent = "Analyse en cours…";
        result.append(spinner, loading);

        try {
            const response = await fetch(panel.dataset.moderationUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken,
                },
                body: JSON.stringify({ text }),
            });
            const data = await response.json();
            if (currentRequest !== requestNumber) return;
            if (!response.ok) {
                throw new Error(data.error || "L’analyse automatique a échoué.");
            }
            const confidence = `${Math.round(data.confidence * 100)} %`;
            result.textContent =
                data.label === "FLAGGED"
                    ? `À vérifier — confiance ${confidence}. L’envoi reste possible.`
                    : `OK — confiance ${confidence}.`;
        } catch (error) {
            if (currentRequest === requestNumber) {
                result.textContent = `Erreur de modération : ${error.message}`;
            }
        }
    }

    title.addEventListener("blur", checkContent);
    description.addEventListener("blur", checkContent);
});
