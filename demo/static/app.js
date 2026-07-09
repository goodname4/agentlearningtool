const parser = new DOMParser();

function setBusy(isBusy) {
  document.body.classList.toggle("is-busy", isBusy);
}

function replacePage(html, nextUrl = null) {
  const nextDocument = parser.parseFromString(html, "text/html");
  const nextShell = nextDocument.querySelector(".shell");
  const currentShell = document.querySelector(".shell");

  if (!nextShell || !currentShell) {
    window.location.reload();
    return;
  }

  currentShell.replaceWith(nextShell);
  if (nextUrl) {
    window.history.pushState({}, "", nextUrl);
  }
  bindSmoothInteractions();
}

async function fetchAndSwap(url, options = {}) {
  setBusy(true);
  try {
    const shouldUpdateUrl = options.updateUrl === true;
    delete options.updateUrl;

    const response = await fetch(url, {
      redirect: "follow",
      headers: {
        "X-Requested-With": "fetch",
        ...(options.headers || {}),
      },
      ...options,
    });

    const html = await response.text();
    replacePage(html, shouldUpdateUrl ? response.url : null);
  } catch (error) {
    console.error(error);
    window.location.href = url;
  } finally {
    setBusy(false);
  }
}

function bindSmoothInteractions() {
  document.querySelectorAll("form:not([data-no-ajax])").forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();

      const submitter = event.submitter || form.querySelector("button[type='submit']");
      if (submitter) {
        submitter.disabled = true;
        submitter.dataset.originalText = submitter.textContent;
        submitter.textContent = "处理中...";
      }

      fetchAndSwap(form.action, {
        method: form.method || "POST",
        body: new FormData(form),
        updateUrl: true,
      });
    });
  });

  document.querySelectorAll("[data-smooth-link]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      fetchAndSwap(link.href, { updateUrl: true });
    });
  });
}

window.addEventListener("popstate", () => {
  fetchAndSwap(window.location.href);
});

document.addEventListener("DOMContentLoaded", bindSmoothInteractions);
