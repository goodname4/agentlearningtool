const parser = new DOMParser();

function setBusy(isBusy) {
  document.body.classList.toggle("is-busy", isBusy);
}

function replacePage(html) {
  const nextDocument = parser.parseFromString(html, "text/html");
  const nextShell = nextDocument.querySelector(".shell");
  const currentShell = document.querySelector(".shell");

  if (!nextShell || !currentShell) {
    window.location.reload();
    return;
  }

  currentShell.replaceWith(nextShell);
  bindPageInteractions();
}

async function fetchAndSwap(url, options = {}) {
  setBusy(true);
  try {
    const response = await fetch(url, {
      redirect: "follow",
      headers: {
        "X-Requested-With": "fetch",
        ...(options.headers || {}),
      },
      ...options,
    });

    const html = await response.text();
    replacePage(html);
  } catch (error) {
    console.error(error);
    window.location.href = url;
  } finally {
    setBusy(false);
  }
}

function bindSmoothInteractions() {
  document.querySelectorAll("form:not([data-no-ajax])").forEach((form) => {
    if (form.dataset.ajaxBound === "true") {
      return;
    }
    form.dataset.ajaxBound = "true";
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
      });
    });
  });

  document.querySelectorAll("[data-smooth-link]").forEach((link) => {
    if (link.dataset.ajaxBound === "true") {
      return;
    }
    link.dataset.ajaxBound = "true";
    link.addEventListener("click", (event) => {
      event.preventDefault();
      fetchAndSwap(link.href);
    });
  });
}

function bindOcrUpload() {
  const ocrBtn = document.getElementById("ocrBtn");
  const ocrFile = document.getElementById("ocrFile");
  const ocrResult = document.getElementById("ocrResult");
  const questionTextarea = document.querySelector('textarea[name="question"]');

  if (!ocrBtn || !ocrFile || !ocrResult || !questionTextarea || ocrBtn.dataset.ocrBound === "true") {
    return;
  }

  ocrBtn.dataset.ocrBound = "true";
  ocrBtn.addEventListener("click", async () => {
    const file = ocrFile.files[0];
    if (!file) {
      alert("请先选择一张图片");
      return;
    }

    const originalText = ocrBtn.textContent;
    const formData = new FormData();
    formData.append("file", file);

    ocrBtn.disabled = true;
    ocrBtn.textContent = "文字识别中...";
    ocrResult.value = "文字识别中...";

    try {
      const response = await fetch("/ocr_upload", {
        method: "POST",
        body: formData,
      });
      const data = await response.json();
      if (!response.ok || data.error) {
        throw new Error(data.error || "OCR请求失败");
      }

      const text = data.text || "未识别到文字";
      ocrResult.value = text;
      questionTextarea.value = text;
      questionTextarea.dispatchEvent(new Event("input"));
    } catch (error) {
      ocrResult.value = "OCR识别失败：" + error.message;
      alert("OCR识别失败：" + error.message);
    } finally {
      ocrBtn.disabled = false;
      ocrBtn.textContent = originalText;
    }
  });
}

function bindTestButtons() {
  document.querySelectorAll(".test-btn").forEach((btn) => {
    if (btn.dataset.testBound === "true") {
      return;
    }
    btn.dataset.testBound = "true";
    btn.addEventListener("click", async function () {
      const idx = this.dataset.index;
      const area = document.getElementById("test-" + idx);
      if (!area) return;

      if (area.style.display !== "none" && area.innerHTML.trim() !== "") {
        area.style.display = "none";
        this.textContent = "测验";
        return;
      }

      this.textContent = "加载中...";
      try {
        const response = await fetch("/test/" + idx);
        const data = await response.json();
        area.innerHTML = `
          <div style="background:#f0f8ff; padding:10px; border-radius:6px; border:1px solid #4CAF50; margin:8px 0;">
            <strong>测验题</strong>
            <p style="margin:8px 0;">${data.test}</p>
            <small>知识点：${data.knowledge_point}</small>
          </div>
        `;
        area.style.display = "block";
        this.textContent = "收起";
        area.scrollIntoView({ behavior: "smooth", block: "center" });
      } catch (error) {
        alert("获取测验题失败");
        this.textContent = "测验";
      }
    });
  });
}

function bindPageInteractions() {
  bindSmoothInteractions();
  bindOcrUpload();
  bindTestButtons();
}

document.addEventListener("DOMContentLoaded", bindPageInteractions);
