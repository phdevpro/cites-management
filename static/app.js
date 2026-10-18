// All page behaviour lives here so the Content-Security-Policy can forbid inline scripts.
// Pages opt in with data-* attributes.
(function () {
  "use strict";

  // Bootstrap classes on Django-rendered form widgets
  function bootstrapify(root) {
    root.querySelectorAll("form input:not([type=checkbox]):not([type=radio]):not([type=hidden]):not(.form-control), form textarea:not(.form-control)")
      .forEach(function (el) { el.classList.add("form-control"); });
    root.querySelectorAll("form select:not(.form-select)").forEach(function (el) { el.classList.add("form-select"); });
    root.querySelectorAll("form input[type=checkbox]:not(.form-check-input)").forEach(function (el) { el.classList.add("form-check-input"); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    bootstrapify(document);

    // <select data-autosubmit>: submit the filter form on change
    document.querySelectorAll("[data-autosubmit]").forEach(function (el) {
      el.addEventListener("change", function () { el.form.submit(); });
    });

    // select-all checkbox for .row-check rows
    var selectAll = document.getElementById("select-all");
    if (selectAll) {
      selectAll.addEventListener("change", function () {
        document.querySelectorAll(".row-check").forEach(function (c) { c.checked = selectAll.checked; });
      });
    }

    // data-busy-text on a form: disable its submit button and show progress while uploading
    document.querySelectorAll("form[data-busy-text]").forEach(function (form) {
      form.addEventListener("submit", function () {
        var btn = form.querySelector("button[type=submit], button:not([type])");
        if (!btn) return;
        btn.disabled = true;
        btn.textContent = form.dataset.busyText;
      });
    });

    // data-auto-refresh="ms": reload (e.g. import progress) unless the user is selecting rows
    var refresh = document.querySelector("[data-auto-refresh]");
    if (refresh) {
      setInterval(function () {
        if (!document.querySelector(".row-check:checked")) location.reload();
      }, parseInt(refresh.dataset.autoRefresh, 10) || 4000);
    }

    // review page: show the fields relevant to the chosen action (sections marked data-for="a b")
    var action = document.getElementById("id_action");
    if (action && document.querySelector("[data-for]")) {
      var sync = function () {
        document.querySelectorAll("[data-for]").forEach(function (el) {
          el.style.display = el.dataset.for.split(" ").indexOf(action.value) >= 0 ? "" : "none";
        });
      };
      action.addEventListener("change", sync);
      sync();
    }

    // data-fill-target / data-fill-value: links that set a field (e.g. pick a candidate declaration)
    document.querySelectorAll("[data-fill-target]").forEach(function (el) {
      el.addEventListener("click", function (e) {
        e.preventDefault();
        var target = document.getElementById(el.dataset.fillTarget);
        if (target) target.value = el.dataset.fillValue;
      });
    });

    // formset rows: button data-formset-add="<prefix>" clones <template id="<prefix>-tpl"> into #<prefix>-body
    document.querySelectorAll("[data-formset-add]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var prefix = btn.dataset.formsetAdd;
        var total = document.getElementById("id_" + prefix + "-TOTAL_FORMS");
        var tpl = document.getElementById(prefix + "-tpl");
        var body = document.getElementById(prefix + "-body");
        body.insertAdjacentHTML("beforeend", tpl.innerHTML.replace(/__prefix__/g, total.value));
        total.value = parseInt(total.value, 10) + 1;
        body.querySelectorAll("input:not(.form-control):not([type=checkbox])").forEach(function (e) { e.classList.add("form-control", "form-control-sm"); });
        body.querySelectorAll("select:not(.form-select)").forEach(function (e) { e.classList.add("form-select", "form-select-sm"); });
      });
    });

    // data-download-text + data-download-name: save text as a file, generated in the browser
    document.querySelectorAll("[data-download-text]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([btn.dataset.downloadText], { type: "text/plain" }));
        a.download = btn.dataset.downloadName || "download.txt";
        a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
      });
    });

    // data-copy="<element id>": copy a field's text to the clipboard, with feedback on the button
    document.querySelectorAll("[data-copy]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var el = document.getElementById(btn.dataset.copy);
        if (!el) return;
        var text = el.value !== undefined ? el.value : el.textContent;
        var label = btn.innerHTML;
        var done = function () {
          btn.innerHTML = "✓ Copiato";
          setTimeout(function () { btn.innerHTML = label; }, 1800);
        };
        var fallback = function () {  // plain-http setups, or clipboard permission denied
          el.focus();
          el.select();
          var ok = false;
          try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
          if (ok) { done(); } else { btn.innerHTML = "Seleziona e copia (Ctrl+C)"; setTimeout(function () { btn.innerHTML = label; }, 2500); }
        };
        if (navigator.clipboard && window.isSecureContext) {
          navigator.clipboard.writeText(text).then(done, fallback);
        } else {
          fallback();
        }
      });
    });

    document.querySelectorAll("[data-print]").forEach(function (btn) {
      btn.addEventListener("click", function () { window.print(); });
    });
  });

  // Confirmations: data-confirm on a button (click) or a form (submit).
  // data-require-selection on a button: at least one .row-check in its form must be ticked.
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("button[data-confirm], button[data-require-selection], a[data-confirm]");
    if (!btn) return;
    if (btn.hasAttribute("data-require-selection")) {
      var form = btn.closest("form");
      if (form && !form.querySelector(".row-check:checked")) {
        e.preventDefault();
        alert("Seleziona almeno un elemento.");
        return;
      }
    }
    if (btn.dataset.confirm && !confirm(btn.dataset.confirm)) e.preventDefault();
  });
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (form.dataset.confirm && !confirm(form.dataset.confirm)) e.preventDefault();
  });
})();
