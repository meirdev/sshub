(function () {
  "use strict";
  const BUNDLE_URL = "/static/core/vendor/codemirror/codemirror.bundle.js";
  async function initCodeMirror(textarea) {
    const {
      EditorView,
      basicSetup,
      EditorState,
      StreamLanguage,
      shell,
      oneDark,
    } = await import(BUNDLE_URL);
    textarea.style.display = "none";
    const view = new EditorView({
      state: EditorState.create({
        doc: textarea.value,
        extensions: [
          basicSetup,
          StreamLanguage.define(shell),
          oneDark,
          EditorView.updateListener.of(function (update) {
            if (update.docChanged) {
              textarea.value = update.state.doc.toString();
            }
          }),
          EditorView.theme({
            "&": { minHeight: "300px", fontSize: "14px", width: "100%" },
            ".cm-scroller": { overflow: "auto" },
          }),
        ],
      }),
    });
    textarea.parentNode.insertBefore(view.dom, textarea.nextSibling);
  }
  function init() {
    document.querySelectorAll("textarea.codemirror").forEach(function (el) {
      if (!el.dataset.cmInit) {
        el.dataset.cmInit = "1";
        initCodeMirror(el);
      }
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
