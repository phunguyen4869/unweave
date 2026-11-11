/* Animated guide. Scenarios are lists of steps; each step builds a GSAP timeline
   against the fake app in guide.html from a clean stage, so back/next/jump never
   depend on what ran before. Without GSAP the page keeps its written steps (see
   .guide-ready in guide.css). Resetting clears inline styles on every .ua element,
   so static looks live in CSS. */
(function () {
  var page = document.getElementById("guide");
  var gsap = window.gsap;
  if (!page || !gsap) return;
  page.classList.add("guide-ready");

  var stage = document.getElementById("guide-stage");
  var ua = stage.querySelector(".ua");
  var cursor = stage.querySelector(".ua-cursor");
  var ripple = stage.querySelector(".ua-ripple");
  var toggle = document.getElementById("player-toggle");
  var back = document.getElementById("player-back");
  var next = document.getElementById("player-next");
  var count = document.getElementById("player-count");
  var segsHost = document.getElementById("player-segs");
  var caption = document.getElementById("guide-caption");
  var nextScenario = document.getElementById("player-scenario");
  var nextScenarioName = document.getElementById("player-scenario-name");
  var scenarioList = document.querySelector(".guide-scenarios");
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var HOLD = 3.4; // seconds to read the finished step before moving on
  var STEM_FILES = ["vocals", "drums", "bass", "guitar", "piano", "other"];
  var scale = 1;
  var narrow = null;
  var scenario = null;
  var current = 0;
  var segs = [];
  var buttons = [];
  var timeline = null;
  var auto = !reduced; // advance to the next step when one ends
  var touched = [];

  function u(name) { return stage.querySelector('[data-u="' + name + '"]'); }
  function all(sel) { return Array.prototype.slice.call(stage.querySelectorAll(sel)); }
  function row(name) { return u("row-" + name); }

  /* ---------- reversible state ---------- */
  function cls(el, name, on) {
    on = on !== false;
    if (el.classList.contains(name) === on) return;
    touched.push([el, name, !on]);
    el.classList.toggle(name, on);
  }
  function resetStage() {
    if (timeline) { timeline.kill(); timeline = null; }
    touched.reverse().forEach(function (t) { t[0].classList.toggle(t[1], t[2]); });
    touched = [];
    var parts = all(".ua *");
    gsap.killTweensOf(parts);
    gsap.set(parts, {clearProps: "all"});
    all("[data-blank]").forEach(function (el) { el.textContent = el.getAttribute("data-blank"); });
    setFiles("", []);
    gsap.set(cursor, {x: 480, y: 300});
  }

  /* ---------- fake app helpers ---------- */
  function screen(name, activeTab) {
    ["setup", "new", "progress", "fail", "song"].forEach(function (id) { cls(u(id), "on", id === name); });
    cls(u("tab-new"), "on", activeTab === "new");
    cls(u("tab-lib"), "on", activeTab === "lib");
  }
  function setFiles(path, items) {
    u("files-path").textContent = path;
    var list = u("files-list");
    list.textContent = "";
    items.forEach(function (item) {
      var li = document.createElement("li");
      li.textContent = item.name;
      li.className = item.kind || "";
      if (item.u) li.setAttribute("data-u", item.u);
      list.appendChild(li);
    });
  }
  function stemFiles(path, extension) {
    setFiles(path, STEM_FILES.map(function (n) { return {name: n + extension}; }));
  }
  function point(el) {
    var box = el.getBoundingClientRect();
    var base = ua.getBoundingClientRect();
    return {x: (box.left + box.width / 2 - base.left) / scale, y: (box.top + box.height / 2 - base.top) / scale};
  }
  function resolve(target) {
    if (typeof target === "function") return target();
    return typeof target === "string" ? u(target) : target;
  }
  function follow(el) {
    var p = point(el);
    gsap.set(cursor, {x: p.x, y: p.y});
  }
  function phases(host, active) {
    Array.prototype.forEach.call(host.children, function (span, i) { cls(span, "on", i === active); });
  }

  /* ---------- timeline verbs ---------- */
  function step(t, fn) { t.call(fn); }
  function wait(t, seconds) { t.to({}, {duration: seconds}); }
  function move(t, target, duration) {
    // Functions measure when the tween starts, after earlier steps changed the layout.
    t.to(cursor, {
      x: function () { return point(resolve(target)).x; },
      y: function () { return point(resolve(target)).y; },
      duration: duration || 0.7,
      ease: "power2.inOut"
    });
  }
  function press(t, fn) {
    t.to(cursor, {scale: 0.82, duration: 0.09});
    t.call(function () {
      gsap.fromTo(ripple,
        {x: gsap.getProperty(cursor, "x"), y: gsap.getProperty(cursor, "y"), scale: 0.3, opacity: 0.9},
        {scale: 1.3, opacity: 0, duration: 0.45, ease: "power1.out"});
      if (fn) fn();
    });
    t.to(cursor, {scale: 1, duration: 0.12});
  }
  function tap(t, target, fn, duration) { move(t, target, duration); press(t, fn); }
  function tween100(t, duration, onValue, position) {
    var value = {v: 0};
    t.to(value, {v: 100, duration: duration, ease: "none", onUpdate: function () { onValue(value.v); }}, position);
  }
  // Move a slider-like element between two percentages with the cursor on it.
  function slide(t, el, from, to, duration, onValue) {
    var value = {v: from};
    t.to(value, {
      v: to,
      duration: duration,
      ease: "power1.inOut",
      onUpdate: function () {
        el.style.left = value.v + "%";
        if (onValue) onValue(value.v);
        follow(el);
      }
    });
  }
  function pop(t, el) {
    t.fromTo(el, {opacity: 0, y: 10}, {opacity: 1, y: 0, duration: 0.25, ease: "power2.out"});
  }
  function dialogPop(t, el) {
    step(t, function () { cls(el, "on"); });
    t.fromTo(el, {opacity: 0, scale: 0.97}, {opacity: 1, scale: 1, duration: 0.22, ease: "power2.out"});
  }
  function toast(t, key) {
    var el = u("toast");
    step(t, function () {
      all(".ua-toast span").forEach(function (s) { cls(s, "on", s.getAttribute("data-t") === key); });
      cls(el, "on");
    });
    pop(t, el);
  }
  function spot(t, el, seconds) {
    step(t, function () { cls(el, "ua-spot"); });
    wait(t, seconds);
    step(t, function () { cls(el, "ua-spot", false); });
  }
  // Drag both handles of a section editor; the highlighted part follows them.
  function trimHandles(t, start, end, sel) {
    move(t, start);
    slide(t, start, 0, 22, 0.8, function (v) { sel.style.left = v + "%"; });
    move(t, end, 0.5);
    slide(t, end, 100, 74, 0.8, function (v) { sel.style.right = (100 - v) + "%"; });
  }
  function trimmed(start, end, sel) {
    start.style.left = "22%";
    end.style.left = "74%";
    sel.style.left = "22%";
    sel.style.right = "26%";
  }
  // The song plays under a step's other actions and through its reading pause.
  // Call last, once the step's length is known.
  function playThrough(t, from, to, position) {
    var heads = all(".ua-playhead"), fill = u("seek-fill"), clock = u("clock"), played = {v: from};
    t.to(played, {
      v: to,
      duration: t.duration() - position + HOLD,
      ease: "none",
      onUpdate: function () {
        var left = played.v * 100 + "%", seconds = Math.round(played.v * 214);
        heads.forEach(function (head) { head.style.left = left; });
        fill.style.width = left;
        clock.textContent = Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0");
      }
    }, position);
  }
  function jobPanel(t, title, seconds, then) {
    var song = u("song"), pct = u("exp-pct");
    step(t, function () { phases(u("job-title"), title); phases(u("job-sub"), title); cls(song, "is-exporting"); });
    t.to(u("exp-bar"), {scaleX: 1, duration: seconds, ease: "power1.inOut"});
    tween100(t, seconds, function (v) { pct.textContent = Math.floor(v) + "%"; }, "<");
    step(t, function () { cls(song, "is-exporting", false); if (then) then(); });
  }
  function separation(t, seconds, toastKey) {
    var ring = u("ring"), pct = u("ring-pct"), pill = u("pill"), pillPct = u("pill-pct");
    var length = 2 * Math.PI * 76;
    var share = function (part) { return "sep+=" + (seconds * part); };
    gsap.set(ring, {strokeDasharray: length, strokeDashoffset: length});
    function at(phase) {
      phases(u("sep-title"), phase);
      phases(u("sep-sub"), phase);
      Array.prototype.forEach.call(u("sep-steps").children, function (li, i) {
        cls(li, "done", i < phase);
        cls(li, "active", i === phase);
      });
    }
    step(t, function () { screen("progress", "new"); phases(u("pill-what"), 0); cls(pill, "on"); at(0); });
    t.addLabel("sep");
    tween100(t, seconds, function (v) {
      gsap.set(ring, {strokeDashoffset: length * (1 - v / 100)});
      pct.textContent = pillPct.textContent = Math.floor(v) + "%";
    });
    t.call(function () { at(1); }, null, share(0.12));
    t.call(function () { at(2); }, null, share(0.36));
    t.call(function () { at(3); }, null, share(0.88));
    step(t, function () { at(4); cls(pill, "on", false); cls(u("sep-cancel"), "ua-hide"); });
    toast(t, toastKey);
  }
  function newWithFile() {
    screen("new", "new");
    cls(u("new"), "has-file");
    gsap.set(cursor, {x: 240, y: 350});
  }
  function songScreen() {
    screen("song", "lib");
    gsap.set(cursor, {x: 480, y: 150});
  }

  /* ---------- steps ---------- */
  function setupStep(t) {
    screen("setup", "new");
    t.from(all(".ua-tile"), {y: 12, opacity: 0, stagger: 0.12, duration: 0.35});
    wait(t, 0.7);
    tap(t, "setup-start", function () { cls(u("setup-start"), "busy"); });
    ["ffmpeg", "separation"].forEach(function (id, i) {
      var tile = u("tile-" + id);
      step(t, function () { cls(tile, "run"); });
      t.to(tile.querySelector(".ua-track i"), {scaleX: 1, duration: i ? 2.4 : 1.1, ease: "power1.inOut"});
      step(t, function () { cls(tile, "run", false); cls(tile, "done"); });
    });
    toast(t, "setup");
  }
  function addFileStep(t) {
    screen("new", "new");
    var ghost = u("ghost"), drop = u("drop");
    gsap.set(cursor, {x: 320, y: 340});
    step(t, function () { cls(ghost, "on"); });
    pop(t, ghost);
    move(t, ghost, 0.6);
    t.to(cursor, {scale: 0.85, duration: 0.1});
    step(t, function () { cls(drop, "dragging"); });
    t.to(ghost, {
      x: function () { return point(drop).x - point(ghost).x; },
      y: function () { return point(drop).y - point(ghost).y; },
      duration: 1.1,
      ease: "power2.inOut",
      onUpdate: function () { follow(ghost); }
    });
    t.to(cursor, {scale: 1, duration: 0.1});
    t.to(ghost, {opacity: 0, scale: 0.8, duration: 0.2});
    step(t, function () { cls(drop, "dragging", false); cls(u("new"), "has-file"); });
    pop(t, u("file"));
    wait(t, 0.6);
    step(t, function () { cls(u("start"), "ua-spot"); });
  }
  function chooseStemsStep(t) {
    newWithFile();
    var piano = u("stem-piano");
    spot(t, u("grid"), 1.5);
    tap(t, piano, function () { cls(piano, "off"); });
    wait(t, 1.3);
    press(t, function () { cls(piano, "off", false); });
    wait(t, 0.4);
    tap(t, "start");
  }
  function separationStep(t) {
    screen("progress", "new");
    gsap.set(cursor, {x: 800, y: 480});
    separation(t, 7.5, "ready");
  }
  function listenStep(t) {
    songScreen();
    tap(t, "play", function () { cls(u("play"), "playing"); });
    t.addLabel("playing");
    wait(t, 2);
    playThrough(t, 0, 0.05, t.labels.playing);
  }
  function stemFilesStep(t) {
    songScreen();
    var reveal = u("reveal"), callout = u("callout");
    gsap.set(cursor, {x: 300, y: 420});
    cls(reveal, "ready");
    cls(callout, "on");
    t.fromTo(callout, {opacity: 0, y: 6}, {opacity: 1, y: 0, duration: 0.3});
    t.fromTo(reveal, {boxShadow: "0 0 0 0 rgba(255,138,61,0.55)"},
      {boxShadow: "0 0 0 12px rgba(255,138,61,0)", duration: 1, repeat: 2, ease: "power1.out"});
    tap(t, reveal, function () {
      cls(reveal, "ready", false);
      cls(callout, "on", false);
      setFiles("My Song", [{name: "stems", kind: "dir", u: "dir-stems"}, {name: "metadata.json", kind: "doc"}, {name: "original.mp3"}]);
    });
    dialogPop(t, u("files"));
    wait(t, 0.6);
    tap(t, function () { return u("dir-stems"); }, function () { cls(u("dir-stems"), "pick"); });
    wait(t, 0.5);
    step(t, function () { stemFiles("My Song / stems", ".flac"); });
  }

  function ytLinkStep(t) {
    screen("new", "new");
    var view = u("new"), url = u("url"), link = "https://www.youtube.com/watch?v=…";
    gsap.set(cursor, {x: 320, y: 350});
    wait(t, 0.3);
    tap(t, "src-yt", function () { cls(view, "is-yt"); });
    tap(t, url);
    tween100(t, 1.2, function (v) { url.textContent = link.slice(0, Math.round(link.length * v / 100)); });
    wait(t, 0.4);
    spot(t, u("trim-first"), 1.4);
    tap(t, "start", function () { cls(view, "is-dl"); });
    t.to(u("dl-bar"), {scaleX: 1, duration: 1.3, ease: "power1.inOut"});
  }
  function ytReady() {
    screen("new", "new");
    cls(u("new"), "is-yt");
    cls(u("new"), "yt-ready");
    gsap.set(cursor, {x: 240, y: 350});
  }
  function ytTrimStep(t) {
    ytReady();
    pop(t, u("trim"));
    wait(t, 0.4);
    trimHandles(t, u("trim-start"), u("trim-end"), u("trim-sel"));
  }
  function ytStartStep(t) {
    ytReady();
    trimmed(u("trim-start"), u("trim-end"), u("trim-sel"));
    wait(t, 0.3);
    tap(t, "start");
    separation(t, 4.5, "ready");
  }

  function soloStep(t) {
    songScreen();
    var vocals = row("vocals");
    function solo(on) {
      all(".ua-row").forEach(function (r) { if (r !== vocals) cls(r, "dim", on); });
      cls(vocals.querySelector(".s"), "on", on);
    }
    tap(t, "play", function () { cls(u("play"), "playing"); });
    t.addLabel("playing");
    tap(t, vocals.querySelector(".s"), function () { solo(true); }, 0.8);
    wait(t, 2);
    press(t, function () { solo(false); });
    playThrough(t, 0, 0.06, t.labels.playing);
  }
  function muteStep(t) {
    songScreen();
    cls(u("play"), "playing");
    var drums = row("drums");
    tap(t, drums.querySelector(".m"), function () {
      cls(drums.querySelector(".m"), "on");
      cls(drums, "muted");
    });
    wait(t, 1);
    playThrough(t, 0.06, 0.1, 0);
  }
  function speedStep(t) {
    songScreen();
    cls(u("play"), "playing");
    var speed = u("speed-val");
    move(t, "speed-thumb");
    slide(t, u("speed-thumb"), 100, 50, 1.1, function (v) { speed.textContent = Math.round(50 + v / 2) + "%"; });
    wait(t, 0.6);
    playThrough(t, 0.1, 0.13, 0);
  }

  function exportChooseStep(t) {
    songScreen();
    gsap.set(cursor, {x: 420, y: 300});
    tap(t, "export-open", function () { cls(u("scrim"), "on"); });
    dialogPop(t, u("export-dialog"));
    wait(t, 0.5);
    tap(t, "fmt-mp3", function () { cls(u("fmt-mp3"), "on"); }, 0.6);
    tap(t, "fmt-flac", function () { cls(u("fmt-flac"), "on", false); }, 0.5);
    wait(t, 0.4);
    tap(t, "export-submit");
  }
  function exportWaitStep(t) {
    songScreen();
    gsap.set(cursor, {x: 760, y: 470});
    jobPanel(t, 0, 3);
  }
  function exportDoneStep(t) {
    songScreen();
    gsap.set(cursor, {x: 420, y: 420});
    var scrim = u("scrim"), done = u("done-dialog");
    cls(scrim, "on");
    dialogPop(t, done);
    wait(t, 1.2);
    tap(t, "done-reveal", function () {
      cls(done, "on", false);
      cls(scrim, "on", false);
      stemFiles("My Song / exports", ".mp3");
    });
    dialogPop(t, u("files"));
  }

  function sectionStep(t) {
    newWithFile();
    cls(u("new"), "show-trim");
    pop(t, u("trim"));
    wait(t, 0.4);
    trimHandles(t, u("trim-start"), u("trim-end"), u("trim-sel"));
  }
  function planStep(t) {
    newWithFile();
    var scrim = u("scrim"), dialog = u("plan-dialog"), act = u("plan-act-piano");
    tap(t, "plan-open", function () { cls(scrim, "on"); });
    dialogPop(t, dialog);
    wait(t, 0.7);
    tap(t, act, function () {
      cls(act, "on");
      cls(u("plan-member"), "on");
      phases(u("plan-foot"), 1);
      phases(u("plan-files"), 1);
    });
    wait(t, 1.3);
    tap(t, "plan-use", function () {
      cls(dialog, "on", false);
      cls(scrim, "on", false);
      cls(u("new"), "is-plan");
    });
    wait(t, 0.5);
    tap(t, "start");
  }
  function planSplitStep(t) {
    newWithFile();
    var scrim = u("scrim"), dialog = u("plan-dialog"), split = u("plan-split");
    tap(t, "plan-open", function () { cls(scrim, "on"); });
    dialogPop(t, dialog);
    wait(t, 0.7);
    tap(t, split, function () {
      cls(split, "on");
      cls(dialog, "split-on");
      phases(u("plan-foot"), 2);
      phases(u("plan-files"), 2);
    });
    wait(t, 1.5);
    tap(t, "plan-use", function () {
      cls(dialog, "on", false);
      cls(scrim, "on", false);
      phases(u("plan-summary"), 1);
      cls(u("new"), "is-plan");
    });
    wait(t, 0.5);
    tap(t, "start");
  }
  function guitarSplitStep(t) {
    songScreen();
    var scrim = u("scrim"), dialog = u("split-dialog");
    tap(t, "split-open", function () { cls(scrim, "on"); });
    dialogPop(t, dialog);
    wait(t, 0.4);
    trimHandles(t, u("split-start"), u("split-end"), u("split-sel"));
    tap(t, "split-submit", function () {
      cls(dialog, "on", false);
      cls(scrim, "on", false);
      phases(u("pill-what"), 1);
      cls(u("pill"), "on");
    });
    jobPanel(t, 1, 2.2, function () {
      cls(u("pill"), "on", false);
      cls(u("song"), "has-leaves");
    });
    toast(t, "split");
    wait(t, 1.6);
    step(t, function () { cls(u("toast"), "on", false); });
  }
  function queueStep(t) {
    newWithFile();
    var pill = u("pill"), name = u("file-name");
    name.textContent = "Second Song.mp3";
    pill.querySelector('[data-u="pill-pct"]').textContent = "35%";
    cls(pill, "on");
    cls(u("new"), "is-queue");
    spot(t, pill, 1.1);
    tap(t, "start", function () { cls(u("pill-wait"), "on"); });
    wait(t, 0.7);
    tap(t, pill, function () { cls(u("scrim"), "on"); });
    dialogPop(t, u("queue-dialog"));
  }

  function reportCopyStep(t) {
    screen("fail", "new");
    gsap.set(cursor, {x: 760, y: 470});
    wait(t, 0.9);
    tap(t, "report-copy", function () { cls(u("report-copy"), "ua-spot"); });
    toast(t, "copied");
  }
  function reportSendStep(t) {
    var address = "facebook.com/um1chc5";
    screen("fail", "new");
    gsap.set(cursor, {x: 760, y: 470});
    spot(t, u("report-facebook"), 1.2);
    tap(t, "report-facebook", function () { setFiles(address, []); });
    dialogPop(t, u("files"));
    wait(t, 0.5);
    step(t, function () {
      setFiles(address, [
        {name: "=== Unweave diagnostics ===", kind: "log"},
        {name: "App version: 1.5.8", kind: "log"},
        {name: "Platform: Windows 11", kind: "log"},
        {name: "Separation failed…", kind: "log"}
      ]);
    });
  }
  function linuxAudioStep(t) {
    songScreen();
    cls(u("song"), "has-banner");
    spot(t, u("banner-open"), 1.1);
    tap(t, "banner-open", function () {
      cls(u("song"), "has-banner", false);
      u("win-title").textContent = "127.0.0.1:8765";
    });
    wait(t, 0.5);
    tap(t, "play", function () { cls(u("play"), "playing"); });
    t.addLabel("playing");
    wait(t, 0.8);
    playThrough(t, 0, 0.03, t.labels.playing);
  }

  var SCENARIOS = {
    basic: [setupStep, addFileStep, chooseStemsStep, separationStep, listenStep, stemFilesStep],
    advanced: [sectionStep, planStep, planSplitStep, guitarSplitStep, queueStep],
    youtube: [ytLinkStep, ytTrimStep, ytStartStep],
    practise: [soloStep, muteStep, speedStep],
    "export": [exportChooseStep, exportWaitStep, exportDoneStep],
    trouble: [reportCopyStep, reportSendStep, linuxAudioStep]
  };
  var ORDER = Object.keys(SCENARIOS);

  /* ---------- player ---------- */
  function item(id) { return scenarioList.querySelector('[data-scenario="' + id + '"]'); }
  function paintCaption() {
    var btn = buttons[current];
    caption.querySelector("strong").innerHTML = btn.querySelector("strong").innerHTML;
    caption.querySelector("span").innerHTML = btn.querySelector("span").innerHTML;
    var following = ORDER[ORDER.indexOf(scenario) + 1];
    if (following) nextScenarioName.innerHTML = item(following).querySelector(".scenario-link").innerHTML;
  }
  function paintChrome() {
    count.textContent = (current + 1) + " / " + buttons.length;
    back.disabled = current === 0;
    next.disabled = current === buttons.length - 1;
    buttons.forEach(function (btn, i) {
      if (i === current) btn.setAttribute("aria-current", "step");
      else btn.removeAttribute("aria-current");
    });
    segs.forEach(function (bar, i) { gsap.set(bar, {scaleX: i < current ? 1 : 0}); });
    paintCaption();
  }
  function setState(state) {
    toggle.setAttribute("data-state", state);
    nextScenario.hidden = state !== "ended" || !ORDER[ORDER.indexOf(scenario) + 1];
  }
  function onStepEnd() {
    if (current === buttons.length - 1) { auto = false; setState("ended"); }
    else if (auto) go(current + 1);
    else setState("paused");
  }
  function go(index) {
    current = index;
    resetStage();
    paintChrome();
    var t = gsap.timeline({paused: true});
    SCENARIOS[scenario][index](t);
    wait(t, HOLD);
    var bar = segs[index];
    t.eventCallback("onUpdate", function () { gsap.set(bar, {scaleX: t.progress()}); });
    timeline = t;
    if (reduced && !auto) {
      // Reduced motion: show the step's finished screen instead of animating to it.
      t.progress(1);
      gsap.killTweensOf(ripple);
      gsap.set(ripple, {opacity: 0});
      gsap.set(bar, {scaleX: 1});
      setState(index === buttons.length - 1 ? "ended" : "paused");
    } else {
      t.eventCallback("onComplete", onStepEnd);
      t.play();
      setState("playing");
    }
  }
  function selectScenario(id) {
    scenario = id;
    auto = !reduced;
    ORDER.forEach(function (other) {
      var li = item(other), active = other === id;
      li.classList.toggle("is-active", active);
      var link = li.querySelector(".scenario-link");
      if (active) {
        link.setAttribute("aria-current", "true");
        // Keep the active tab in view when the sidebar is a scrolling row of tabs.
        if (scenarioList.scrollWidth > scenarioList.clientWidth) scenarioList.scrollLeft = li.offsetLeft - 16;
      } else {
        link.removeAttribute("aria-current");
      }
    });
    buttons = Array.prototype.slice.call(item(id).querySelectorAll(".chapter-btn"));
    segsHost.textContent = "";
    segs = buttons.map(function (_, i) {
      var seg = document.createElement("button");
      seg.type = "button";
      seg.className = "player-seg";
      seg.setAttribute("aria-label", String(i + 1));
      seg.innerHTML = "<i><b></b></i>";
      seg.addEventListener("click", function () { go(i); });
      segsHost.appendChild(seg);
      return seg.querySelector("b");
    });
    go(0);
  }
  function scenarioFromHash() {
    var id = location.hash.slice(1);
    return Object.prototype.hasOwnProperty.call(SCENARIOS, id) ? id : ORDER[0];
  }

  toggle.addEventListener("click", function () {
    var state = toggle.getAttribute("data-state");
    if (state === "ended") {
      auto = true;
      go(0);
    } else if (state === "playing") {
      auto = false;
      timeline.pause();
      setState("paused");
    } else {
      auto = true;
      if (timeline.progress() >= 1) go(current + 1);
      else { timeline.play(); setState("playing"); }
    }
  });
  back.addEventListener("click", function () { go(Math.max(0, current - 1)); });
  next.addEventListener("click", function () { go(Math.min(buttons.length - 1, current + 1)); });
  nextScenario.addEventListener("click", function () {
    location.hash = ORDER[ORDER.indexOf(scenario) + 1];
  });
  ORDER.forEach(function (id) {
    Array.prototype.forEach.call(item(id).querySelectorAll(".chapter-btn"), function (btn, i) {
      btn.addEventListener("click", function () { go(i); });
    });
  });
  window.addEventListener("hashchange", function () {
    var id = scenarioFromHash();
    if (id !== scenario) selectScenario(id);
  });
  document.addEventListener("keydown", function (e) {
    if (e.target.closest && e.target.closest("dialog, input, textarea, select")) return;
    if (e.key === "ArrowRight" && current < buttons.length - 1) go(current + 1);
    else if (e.key === "ArrowLeft" && current > 0) go(current - 1);
  });
  document.addEventListener("site:lang", paintCaption);

  /* ---------- sizing ---------- */
  function drawWaves() {
    all(".ua-wave").forEach(function (host, n) {
      var bars = "", seed = 7 + n * 13;
      for (var i = 0; i < 70; i++) {
        seed = (seed * 31 + 11) % 97;
        var envelope = 0.35 + 0.65 * Math.abs(Math.sin(i / (6 + n)));
        var height = Math.max(2, envelope * (6 + seed / 97 * 20));
        bars += '<rect x="' + (i * 4) + '" y="' + (13 - height / 2).toFixed(1) + '" width="2.4" height="' + height.toFixed(1) + '" rx="1"/>';
      }
      host.innerHTML = '<svg viewBox="0 0 280 26" preserveAspectRatio="none" fill="currentColor" aria-hidden="true">' + bars + '</svg><i class="ua-playhead"></i>';
    });
  }
  // Returns true when the layout flipped and every measured position is stale.
  function fit() {
    var width = stage.clientWidth;
    var isNarrow = width < 620;
    var flipped = narrow !== null && isNarrow !== narrow;
    narrow = isNarrow;
    stage.classList.toggle("is-narrow", isNarrow);
    scale = width / (isNarrow ? 520 : 960);
    ua.style.transform = "scale(" + scale + ")";
    stage.style.height = (isNarrow ? 800 : 600) * scale + "px";
    return flipped;
  }
  drawWaves();
  fit();
  window.addEventListener("resize", function () { if (fit()) go(current); });
  selectScenario(scenarioFromHash());
})();
