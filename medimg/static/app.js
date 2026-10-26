(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var state = {
    status: null, galleryVersion: -1, sheet: null, sheetLoaded: false,
    selNode: { subject: "", unit: "", lecture: "" }, images: [], current: null,
    lastJobId: null, polling: false, estTimer: null, busy: false
  };

  // ---------- helpers ----------
  function api(method, url, body, isForm) {
    var opt = { method: method, headers: { "X-Medimg": "1" } };
    if (body !== undefined && body !== null) {
      if (isForm) { opt.body = body; }
      else { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    }
    return fetch(url, opt).then(function (r) {
      return r.text().then(function (t) {
        var data = null;
        try { data = t ? JSON.parse(t) : null; } catch (e) { data = null; }
        if (!r.ok) {
          var e2 = (data && data.error) || {};
          var err = new Error(e2.cause || ("The server answered with an error (" + r.status + ")."));
          err.cause = e2.cause || ("The server answered with an error (" + r.status + ").");
          err.fix = e2.fix || "Try again. If it keeps happening, restart the app.";
          throw err;
        }
        return data;
      });
    }, function () {
      var err = new Error("Cannot reach the app.");
      err.cause = "Cannot reach the local server.";
      err.fix = "Check that the start script is still running, then reload this page.";
      throw err;
    });
  }
  function showErr(id, err) {
    var el = $(id);
    el.textContent = "";
    var b = document.createElement("b");
    b.textContent = (err.cause || err.message || "Something went wrong.");
    el.appendChild(b);
    el.appendChild(document.createTextNode(" How to fix: " + (err.fix || "try again.")));
    el.hidden = false;
  }
  function clearErr(id) { var el = $(id); el.hidden = true; el.textContent = ""; }
  function el(tag, text, cls) {
    var e = document.createElement(tag);
    if (text !== undefined && text !== null) { e.textContent = text; }
    if (cls) { e.className = cls; }
    return e;
  }
  function fmtTime(s) {
    if (s === null || s === undefined || isNaN(s)) { return ""; }
    s = Math.round(s);
    if (s < 60) { return s + " s"; }
    var m = Math.floor(s / 60);
    if (m < 60) { return m + " min " + (s % 60) + " s"; }
    return Math.floor(m / 60) + " h " + (m % 60) + " min";
  }
  function mins(s) { return Math.max(1, Math.round(s / 60)); }
  function parseSize(v) {
    var p = String(v).split("x");
    return { width: parseInt(p[0], 10), height: parseInt(p[1], 10) };
  }
  function randomSeed() { return Math.floor(Math.random() * 2147483647); }
  function qs(o) {
    var parts = [];
    Object.keys(o).forEach(function (k) {
      if (o[k] !== "" && o[k] !== null && o[k] !== undefined) {
        parts.push(encodeURIComponent(k) + "=" + encodeURIComponent(o[k]));
      }
    });
    return parts.length ? "?" + parts.join("&") : "";
  }

  // ---------- tabs ----------
  function showTab(name) {
    ["batch", "single", "gallery", "device"].forEach(function (t) {
      $("tab-" + t).hidden = (t !== name);
      $("tab-btn-" + t).classList.toggle("active", t === name);
    });
    if (name === "gallery") { loadGallery(); }
    if (name === "device") { loadDevice(); loadSettings(); }
  }

  // ---------- status strip ----------
  var PHASES = {
    queued: "Waiting to start", loading: "Loading the model", encoding: "Reading the prompt",
    denoising: "Drawing the image", decoding: "Finishing the image", saving: "Saving"
  };
  var MODEL = { not_loaded: "not loaded", loading: "loading", ready: "ready", error: "error" };

  function renderStatus(s) {
    clearErr("st-error");
    $("st-model").textContent = MODEL[s.model.state] || s.model.state;
    if (s.model.state === "error" && s.model.error) {
      showErr("st-error", { cause: "The model failed to load: " + s.model.error, fix: "Run the setup script again, then restart the app." });
    }
    var job = s.job;
    var active = !!job;
    state.busy = active;
    if (job) {
      $("st-phase").textContent = (PHASES[job.phase] || job.phase) + " (" + job.kind + ")";
      var pct = job.step_total ? Math.round(100 * job.step / job.step_total) : 0;
      $("st-bar-fill").style.width = pct + "%";
      $("st-bar").setAttribute("aria-valuenow", String(pct));
      $("st-bar-text").textContent = job.step_total ? ("step " + job.step + " of " + job.step_total) : "";
      $("st-image").textContent = job.image_count ? ("image " + job.image_index + " of " + job.image_count + " in this batch") : "";
      $("st-eta").textContent = (job.eta_s !== null && job.eta_s !== undefined) ? ("about " + fmtTime(job.eta_s) + " left") : "";
    } else {
      var lj = s.last_job;
      $("st-phase").textContent = lj ? ("Idle. Last job " + (lj.outcome === "done" ? "finished" : lj.outcome) + ".") : "Idle";
      $("st-bar-fill").style.width = "0";
      $("st-bar").setAttribute("aria-valuenow", "0");
      $("st-bar-text").textContent = "";
      $("st-image").textContent = "";
      $("st-eta").textContent = "";
    }
    ["b-generate", "s-generate", "d-bench", "lb-regen"].forEach(function (id) { $(id).disabled = active; });
    $("b-cancel").disabled = !active;
    $("st-local").textContent = s.local_only === false ? "NOT local" : "local only";

    if (s.gallery_version !== state.galleryVersion) {
      state.galleryVersion = s.gallery_version;
      if (!$("tab-gallery").hidden) { loadGallery(); }
    }
    var lid = s.last_job ? s.last_job.id : null;
    if (lid !== state.lastJobId) {
      var first = state.lastJobId === null && state.status === null;
      state.lastJobId = lid;
      if (!first) {
        if (state.sheetLoaded) { refreshSheet(); }
        if (!$("tab-device").hidden) { loadDevice(); }
      }
    }
    if (job && job.errors && job.errors.length) {
      var msgs = job.errors.map(function (e) { return "row " + e.row + ": " + e.reason; }).join("; ");
      showErr("b-err", { cause: "Some rows failed: " + msgs, fix: "Fix the cause, tick Retry failed rows, and run the batch again." });
    }
    state.status = s;
  }

  function poll() {
    if (state.polling) { return; }
    state.polling = true;
    api("GET", "/api/status").then(renderStatus, function (e) {
      showErr("st-error", e);
    }).then(function () { state.polling = false; });
  }

  // ---------- config ----------
  function applyConfig(c) {
    if (c.size_presets && c.size_presets.length) {
      [$("s-size"), $("b-size")].forEach(function (sel) {
        sel.textContent = "";
        c.size_presets.forEach(function (p) {
          var o = el("option", p.label);
          o.value = p.width + "x" + p.height;
          sel.appendChild(o);
        });
      });
    }
    if (c.limits) {
      $("s-steps").min = c.limits.steps_min; $("s-steps").max = c.limits.steps_max;
    }
    if (c.defaults) {
      $("s-steps").value = c.defaults.steps; $("s-steps-val").textContent = c.defaults.steps;
    }
  }

  // ---------- Tab A: batch ----------
  function filterObj() {
    return {
      subject: $("b-filter-subject").value, unit: $("b-filter-unit").value, lecture: $("b-filter-lecture").value
    };
  }
  function fillSelect(id, first, values) {
    var sel = $(id), keep = sel.value;
    sel.textContent = "";
    var o = el("option", first); o.value = ""; sel.appendChild(o);
    (values || []).forEach(function (v) { var x = el("option", v); x.value = v; sel.appendChild(x); });
    sel.value = keep;
  }
  function renderSheet(r, fresh) {
    state.sheet = r; state.sheetLoaded = true;
    $("b-summary").textContent = "Loaded: " + r.original_name;
    var c = r.counts || {};
    ["total", "done", "pending", "blocked", "failed", "invalid"].forEach(function (k) {
      $("c-" + k).textContent = c[k] || 0;
    });
    var body = $("b-problems-body");
    body.textContent = "";
    var probs = r.problems || [];
    probs.forEach(function (p) {
      var tr = el("tr");
      tr.appendChild(el("td", p.row));
      tr.appendChild(el("td", p.reason));
      tr.appendChild(el("td", p.fix));
      body.appendChild(tr);
    });
    $("b-problems").hidden = probs.length === 0;
    if (fresh) {
      var f = r.filters || {};
      fillSelect("b-filter-subject", "All subjects", f.subjects);
      fillSelect("b-filter-unit", "All units", f.units);
      fillSelect("b-filter-lecture", "All lectures", f.lectures);
    }
    var pending = c.pending || 0;
    $("b-count").max = Math.max(1, pending);
    if (r.suggested_batch) { $("b-count").value = r.suggested_batch; }
    updateEstimate();
  }
  function sheetQuery() {
    var f = filterObj();
    return qs({
      retry_failed: $("b-retry").checked ? "true" : "false", default_size: $("b-size").value,
      subject: f.subject, unit: f.unit, lecture: f.lecture
    });
  }
  function refreshSheet() {
    api("GET", "/api/sheet" + sheetQuery()).then(function (r) { renderSheet(r, false); clearErr("b-err"); },
      function (e) { showErr("b-err", e); });
  }
  function upload() {
    clearErr("b-upload-err");
    var file = $("b-file").files[0];
    if (!file) {
      showErr("b-upload-err", { cause: "No file chosen.", fix: "Click the file box and pick your .xlsx spreadsheet." });
      return;
    }
    var fd = new FormData();
    fd.append("file", file);
    fd.append("retry_failed", $("b-retry").checked ? "true" : "false");
    fd.append("default_size", $("b-size").value);
    api("POST", "/api/sheet", fd, true).then(function (r) { renderSheet(r, true); },
      function (e) { showErr("b-upload-err", e); });
  }
  function updateEstimate() {
    clearTimeout(state.estTimer);
    state.estTimer = setTimeout(function () {
      var n = parseInt($("b-count").value, 10);
      if (!state.sheetLoaded || !(n > 0)) { $("b-estimate").textContent = ""; return; }
      api("POST", "/api/sheet/estimate", {
        count: n, filter: filterObj(), steps: parseInt($("s-steps").value, 10), default_size: $("b-size").value
      }).then(function (r) {
        $("b-estimate").textContent = r.count + " images ≈ " + mins(r.seconds) + " min on this machine";
      }, function (e) { showErr("b-err", e); });
    }, 250);
  }
  function generateBatch() {
    clearErr("b-err");
    if (!state.sheetLoaded) {
      showErr("b-err", { cause: "No sheet loaded.", fix: "Upload an .xlsx file first." });
      return;
    }
    var n = parseInt($("b-count").value, 10);
    if (!(n > 0)) {
      showErr("b-err", { cause: "The number of images must be at least 1.", fix: "Type a number such as 5 in the box." });
      return;
    }
    api("POST", "/api/jobs/batch", {
      count: n, filter: filterObj(), retry_failed: $("b-retry").checked,
      default_size: $("b-size").value, steps: parseInt($("s-steps").value, 10)
    }).then(function () { poll(); }, function (e) { showErr("b-err", e); });
  }
  function cancelJob(errId) {
    api("POST", "/api/jobs/cancel").then(function () { poll(); }, function (e) { showErr(errId, e); });
  }

  // ---------- Tab B: single ----------
  function generateSingle() {
    clearErr("s-err"); $("s-result").textContent = "";
    var prompt = $("s-prompt").value.trim();
    if (!prompt) {
      showErr("s-err", { cause: "The prompt is empty.", fix: "Type what the image should show." });
      return;
    }
    var seedTxt = $("s-seed").value.trim();
    var sz = parseSize($("s-size").value);
    api("POST", "/api/jobs/single", {
      prompt: prompt, seed: seedTxt === "" ? null : parseInt(seedTxt, 10),
      steps: parseInt($("s-steps").value, 10), width: sz.width, height: sz.height,
      subject: $("s-subject").value.trim(), unit: $("s-unit").value.trim(),
      lecture: $("s-lecture").value.trim(), image_name: $("s-name").value.trim()
    }).then(function (r) {
      $("s-result").textContent = "Started. It will be saved as " + r.rel_path + ". Watch the bar at the top.";
      poll();
    }, function (e) { showErr("s-err", e); });
  }

  // ---------- Tab C: gallery ----------
  function loadGallery() {
    api("GET", "/api/gallery/tree").then(function (t) { renderTree(t); clearErr("g-err"); },
      function (e) { showErr("g-err", e); });
    loadImages();
  }
  function selectNode(subject, unit, lecture, title) {
    state.selNode = { subject: subject, unit: unit, lecture: lecture };
    $("g-title").textContent = title;
    loadGallery();
  }
  function nodeButton(label, count, handler, selected) {
    var b = el("button", label + (count !== undefined ? " (" + count + ")" : ""), "node" + (selected ? " sel" : ""));
    b.addEventListener("click", handler);
    return b;
  }
  function renderTree(t) {
    var root = $("g-tree"), sn = state.selNode;
    root.textContent = "";
    root.appendChild(nodeButton("Everything", undefined, function () { selectNode("", "", "", "Everything"); },
      !sn.subject && !sn.unit && !sn.lecture));
    if (t.single_count) {
      root.appendChild(nodeButton("Single images", t.single_count, function () {
        selectNode("_single", "", "", "Single images");
      }, sn.subject === "_single"));
    }
    (t.subjects || []).forEach(function (s) {
      var ds = el("details"); ds.open = sn.subject === s.name;
      var ss = el("summary", s.name); ds.appendChild(ss);
      ss.addEventListener("click", function () { selectNode(s.name, "", "", s.name); });
      (s.units || []).forEach(function (u) {
        var du = el("details"); du.open = sn.subject === s.name && sn.unit === u.name;
        var su = el("summary", u.name); du.appendChild(su);
        su.addEventListener("click", function () { selectNode(s.name, u.name, "", s.name + " / " + u.name); });
        (u.lectures || []).forEach(function (l) {
          du.appendChild(nodeButton(l.name, l.count, function () {
            selectNode(s.name, u.name, l.name, s.name + " / " + u.name + " / " + l.name);
          }, sn.subject === s.name && sn.unit === u.name && sn.lecture === l.name));
        });
        ds.appendChild(du);
      });
      root.appendChild(ds);
    });
  }
  function loadImages() {
    api("GET", "/api/gallery/images" + qs(state.selNode)).then(function (list) {
      state.images = list;
      var grid = $("g-grid");
      grid.textContent = "";
      $("g-empty").hidden = list.length > 0;
      list.forEach(function (it) {
        var fig = el("figure");
        var img = el("img"); img.src = it.thumb_url; img.alt = it.image_name; img.loading = "lazy";
        fig.appendChild(img);
        fig.appendChild(el("figcaption", it.image_name));
        fig.addEventListener("click", function () { openLightbox(it); });
        grid.appendChild(fig);
      });
      if (state.current) {
        var still = list.filter(function (x) { return x.id === state.current.id; })[0];
        if (still && !$("lightbox").hidden) { $("lb-img").src = still.url + "?v=" + state.galleryVersion; fillMeta(still.record); }
      }
      clearErr("g-err");
    }, function (e) { showErr("g-err", e); });
  }
  function fillMeta(r) {
    var dl = $("lb-meta");
    dl.textContent = "";
    var rows = [
      ["Prompt", r.prompt], ["Seed", r.seed], ["Steps", r.steps], ["Size", r.width + " x " + r.height],
      ["Model", r.model_id], ["Time", fmtTime(r.time_s)], ["Date", r.created_at], ["Machine", r.machine],
      ["Saved as", r.rel_path]
    ];
    rows.forEach(function (p) { dl.appendChild(el("dt", p[0])); dl.appendChild(el("dd", String(p[1]))); });
  }
  function openLightbox(it) {
    state.current = it;
    clearErr("lb-err");
    $("lb-img").src = it.url;
    fillMeta(it.record);
    $("lightbox").hidden = false;
  }
  function closeLightbox() { $("lightbox").hidden = true; state.current = null; }
  function regenerate() {
    if (!state.current) { return; }
    clearErr("lb-err");
    if (!window.confirm("Make a new image with a new seed? This replaces the current file" +
      (state.current.record.sheet ? " and updates its row in the sheet." : "."))) { return; }
    api("POST", "/api/jobs/regenerate", { image_id: state.current.id }).then(function () { poll(); },
      function (e) { showErr("lb-err", e); });
  }
  function reuse() {
    if (!state.current) { return; }
    var r = state.current.record;
    $("s-prompt").value = r.prompt;
    $("s-seed").value = r.seed;
    $("s-steps").value = r.steps; $("s-steps-val").textContent = r.steps;
    var v = r.width + "x" + r.height, sel = $("s-size"), found = false, i;
    for (i = 0; i < sel.options.length; i++) { if (sel.options[i].value === v) { found = true; } }
    if (!found) { var o = el("option", v); o.value = v; sel.appendChild(o); }
    sel.value = v;
    $("s-subject").value = ""; $("s-unit").value = ""; $("s-lecture").value = ""; $("s-name").value = "";
    closeLightbox();
    showTab("single");
  }
  function openFolder() {
    if (!state.current) { return; }
    clearErr("lb-err");
    api("POST", "/api/images/" + state.current.id + "/open-folder").then(function (r) {
      if (!r.ok) { showErr("lb-err", { cause: "The folder could not be opened.", fix: "Open the output folder yourself: " + $("set-root").value }); }
    }, function (e) { showErr("lb-err", e); });
  }

  // ---------- Tab D: device ----------
  function loadDevice() {
    api("GET", "/api/device").then(function (d) {
      $("d-unverified").hidden = !d.unverified;
      $("d-report").textContent = d.report || "No device report yet. Click Re-run benchmark.";
      var body = $("d-table-body");
      body.textContent = "";
      (d.estimates || []).forEach(function (r) {
        var tr = el("tr");
        tr.appendChild(el("td", r.label));
        [r.seconds, r.for_10, r.for_25, r.for_50].forEach(function (v) { tr.appendChild(el("td", fmtTime(v))); });
        body.appendChild(tr);
      });
      clearErr("d-err");
    }, function (e) { showErr("d-err", e); });
  }
  function benchmark() {
    clearErr("d-err");
    api("POST", "/api/device/benchmark").then(function () { poll(); }, function (e) { showErr("d-err", e); });
  }
  function loadSettings() {
    api("GET", "/api/settings").then(function (s) {
      $("set-root").value = s.output_root;
      $("set-unload").value = s.unload_after_job === null || s.unload_after_job === undefined ? "auto" : (s.unload_after_job ? "yes" : "no");
    }, function (e) { showErr("set-err", e); });
  }
  function saveSettings() {
    clearErr("set-err"); $("set-ok").hidden = true;
    var u = $("set-unload").value;
    api("PUT", "/api/settings", {
      output_root: $("set-root").value.trim(),
      steps: parseInt($("s-steps").value, 10),
      unload_after_job: u === "auto" ? null : (u === "yes")
    }).then(function () { $("set-ok").hidden = false; state.galleryVersion = -1; poll(); },
      function (e) { showErr("set-err", e); });
  }

  // ---------- wiring ----------
  function init() {
    ["batch", "single", "gallery", "device"].forEach(function (t) {
      $("tab-btn-" + t).addEventListener("click", function () { showTab(t); });
    });
    $("b-upload").addEventListener("click", upload);
    $("b-generate").addEventListener("click", generateBatch);
    $("b-cancel").addEventListener("click", function () { cancelJob("b-err"); });
    $("b-download").addEventListener("click", function () { window.location.href = "/api/sheet/download"; });
    $("b-count").addEventListener("input", updateEstimate);
    ["b-filter-subject", "b-filter-unit", "b-filter-lecture", "b-size", "b-retry"].forEach(function (id) {
      $(id).addEventListener("change", function () { if (state.sheetLoaded) { refreshSheet(); } });
    });
    $("s-steps").addEventListener("input", function () { $("s-steps-val").textContent = $("s-steps").value; });
    $("s-random").addEventListener("click", function () { $("s-seed").value = randomSeed(); });
    $("s-generate").addEventListener("click", generateSingle);
    $("lb-close").addEventListener("click", closeLightbox);
    $("lightbox").addEventListener("click", function (e) { if (e.target === $("lightbox")) { closeLightbox(); } });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") { closeLightbox(); } });
    $("lb-regen").addEventListener("click", regenerate);
    $("lb-reuse").addEventListener("click", reuse);
    $("lb-folder").addEventListener("click", openFolder);
    $("d-bench").addEventListener("click", benchmark);
    $("set-save").addEventListener("click", saveSettings);

    api("GET", "/api/config").then(applyConfig, function (e) { showErr("st-error", e); });
    loadSettings();
    api("GET", "/api/sheet" + sheetQuery()).then(function (r) { renderSheet(r, true); }, function () { /* none loaded yet */ });
    poll();
    setInterval(poll, 500);
  }

  init();
})();
