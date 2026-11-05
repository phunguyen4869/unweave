/* Animated guide. Each chapter builds a GSAP timeline against the fake app in
   guide.html, from a clean stage, so back/next/jump never depend on what ran before.
   Without GSAP the page keeps its written steps (see .guide-ready in guide.css).
   Resetting clears inline styles on every .ua element, so static looks live in CSS. */
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
  var chapterButtons = Array.prototype.slice.call(document.querySelectorAll(".chapter-btn"));
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var HOLD = 3.4; // seconds to read the finished step before moving on
  var STEM_FILES = ["vocals", "drums", "bass", "guitar", "piano", "other"];
  var scale = 1;
  var narrow = null;
  var current = 0;
  var timeline = null;
  var auto = !reduced; // advance to the next chapter when one ends
  var touched = [];

  function u(name) { return stage.querySelector('[data-u="' + name + '"]'); }
  function all(sel) { return Array.prototype.slice.call(stage.querySelectorAll(sel)); }

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
    cls(u(name), "on");
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
  function phases(host, active) {
    Array.prototype.forEach.call(host.children, function (span, i) { cls(span, "on", i === active); });
  }
  function steps(host, active) {
    Array.prototype.forEach.call(host.children, function (li, i) {
      cls(li, "done", i < active);
      cls(li, "active", i === active);
    });
  }

  /* ---------- chapters ---------- */
  var chapters = [
    function setup(t) {
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
    },

    function addFile(t) {
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
    },

    function youtube(t) {
      screen("new", "new");
      var view = u("new"), url = u("url"), link = "https://www.youtube.com/watch?v=…";
      gsap.set(cursor, {x: 320, y: 350});
      wait(t, 0.3);
      tap(t, "src-yt", function () { cls(view, "is-yt"); });
      tap(t, url);
      tween100(t, 1.2, function (v) { url.textContent = link.slice(0, Math.round(link.length * v / 100)); });
      wait(t, 0.4);
      step(t, function () { cls(u("trim-first"), "ua-spot"); });
      wait(t, 1.4);
      step(t, function () { cls(u("trim-first"), "ua-spot", false); });
      tap(t, "start", function () { cls(view, "is-dl"); });
      t.to(u("dl-bar"), {scaleX: 1, duration: 1.3, ease: "power1.inOut"});
      step(t, function () { cls(view, "is-dl", false); cls(view, "yt-ready"); });
      pop(t, u("trim"));
      wait(t, 0.4);
      var sel = u("trim-sel");
      move(t, "trim-start");
      slide(t, u("trim-start"), 0, 22, 0.8, function (v) { sel.style.left = v + "%"; });
      move(t, "trim-end", 0.5);
      slide(t, u("trim-end"), 100, 74, 0.8, function (v) { sel.style.right = (100 - v) + "%"; });
    },

    function stems(t) {
      screen("new", "new");
      cls(u("new"), "has-file");
      var view = u("new"), grid = u("grid"), piano = u("stem-piano");
      gsap.set(cursor, {x: 240, y: 350});
      step(t, function () { cls(grid, "ua-spot"); });
      wait(t, 1.5);
      step(t, function () { cls(grid, "ua-spot", false); });
      tap(t, piano, function () { cls(piano, "off"); });
      wait(t, 1.3);
      press(t, function () { cls(piano, "off", false); });
      tap(t, "preset-vocals", function () {
        cls(view, "is-vocals"); cls(u("preset-vocals"), "on"); cls(u("preset-custom"), "on", false);
      });
      wait(t, 1.3);
      tap(t, "preset-custom", function () {
        cls(view, "is-vocals", false); cls(u("preset-vocals"), "on", false); cls(u("preset-custom"), "on");
      });
      wait(t, 0.4);
      tap(t, "start");
    },

    function separate(t) {
      screen("progress", "new");
      gsap.set(cursor, {x: 800, y: 480});
      var ring = u("ring"), pct = u("ring-pct"), pill = u("pill"), pillPct = u("pill-pct");
      var length = 2 * Math.PI * 76;
      gsap.set(ring, {strokeDasharray: length, strokeDashoffset: length});
      function at(phase) { phases(u("sep-title"), phase); phases(u("sep-sub"), phase); steps(u("sep-steps"), phase); }
      cls(pill, "on");
      at(0);
      tween100(t, 7.5, function (v) {
        gsap.set(ring, {strokeDashoffset: length * (1 - v / 100)});
        pct.textContent = pillPct.textContent = Math.floor(v) + "%";
      });
      t.call(function () { at(1); }, null, 0.9);
      t.call(function () { at(2); }, null, 2.8);
      t.call(function () { at(3); }, null, 6.6);
      step(t, function () { at(4); cls(pill, "on", false); cls(u("sep-cancel"), "ua-hide"); });
      toast(t, "ready");
    },

    function mix(t) {
      screen("song", "lib");
      gsap.set(cursor, {x: 480, y: 120});
      var vocals = u("row-vocals"), drums = u("row-drums"), speed = u("speed-val");
      function solo(on) {
        all(".ua-row").forEach(function (row) { if (row !== vocals) cls(row, "dim", on); });
        cls(vocals.querySelector(".s"), "on", on);
      }
      tap(t, "play", function () { cls(u("play"), "playing"); });
      t.addLabel("playing");
      tap(t, vocals.querySelector(".s"), function () { solo(true); }, 0.8);
      wait(t, 1.5);
      press(t, function () { solo(false); });
      tap(t, drums.querySelector(".m"), function () {
        cls(drums.querySelector(".m"), "on"); cls(drums, "dim");
      }, 0.5);
      wait(t, 1.3);
      move(t, "speed-thumb");
      slide(t, u("speed-thumb"), 100, 50, 1, function (v) { speed.textContent = Math.round(50 + v / 2) + "%"; });
      // The song keeps playing under all of the above and through the reading pause.
      var heads = all(".ua-playhead"), fill = u("seek-fill"), clock = u("clock"), played = {v: 0};
      t.to(played, {
        v: 0.1,
        duration: t.duration() - t.labels.playing + HOLD,
        ease: "none",
        onUpdate: function () {
          var left = played.v * 100 + "%", seconds = Math.round(played.v * 214);
          heads.forEach(function (head) { head.style.left = left; });
          fill.style.width = left;
          clock.textContent = Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0");
        }
      }, "playing");
    },

    function files(t) {
      screen("song", "lib");
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
      step(t, function () {
        setFiles("My Song / stems", STEM_FILES.map(function (n) { return {name: n + ".flac"}; }));
      });
    },

    function exportStems(t) {
      screen("song", "lib");
      gsap.set(cursor, {x: 420, y: 300});
      var song = u("song"), scrim = u("scrim"), dialog = u("export-dialog"), done = u("done-dialog"), pct = u("exp-pct");
      tap(t, "export-open", function () { cls(scrim, "on"); });
      dialogPop(t, dialog);
      wait(t, 0.5);
      tap(t, "fmt-mp3", function () { cls(u("fmt-mp3"), "on"); }, 0.6);
      tap(t, "fmt-flac", function () { cls(u("fmt-flac"), "on", false); }, 0.5);
      wait(t, 0.4);
      tap(t, "export-submit", function () {
        cls(dialog, "on", false); cls(scrim, "on", false); cls(song, "is-exporting");
      });
      t.to(u("exp-bar"), {scaleX: 1, duration: 1.8, ease: "power1.inOut"});
      tween100(t, 1.8, function (v) { pct.textContent = Math.floor(v) + "%"; }, "<");
      step(t, function () { cls(song, "is-exporting", false); cls(scrim, "on"); });
      dialogPop(t, done);
      wait(t, 1.2);
      tap(t, "done-reveal", function () {
        cls(done, "on", false);
        cls(scrim, "on", false);
        setFiles("My Song / exports", STEM_FILES.map(function (n) { return {name: n + ".mp3"}; }));
      });
      dialogPop(t, u("files"));
    }
  ];

  /* ---------- player ---------- */
  var segs = chapters.map(function (_, i) {
    var seg = document.createElement("button");
    seg.type = "button";
    seg.className = "player-seg";
    seg.setAttribute("aria-label", String(i + 1));
    seg.innerHTML = "<i><b></b></i>";
    seg.addEventListener("click", function () { go(i); });
    segsHost.appendChild(seg);
    return seg.querySelector("b");
  });

  function paintCaption() {
    var btn = chapterButtons[current];
    caption.querySelector("strong").innerHTML = btn.querySelector("strong").innerHTML;
    caption.querySelector("span").innerHTML = btn.querySelector("span").innerHTML;
  }
  function paintChrome() {
    count.textContent = (current + 1) + " / " + chapters.length;
    back.disabled = current === 0;
    next.disabled = current === chapters.length - 1;
    chapterButtons.forEach(function (btn, i) {
      if (i === current) btn.setAttribute("aria-current", "step");
      else btn.removeAttribute("aria-current");
    });
    segs.forEach(function (bar, i) { gsap.set(bar, {scaleX: i < current ? 1 : 0}); });
    paintCaption();
  }
  function setState(state) { toggle.setAttribute("data-state", state); }
  function onChapterEnd() {
    if (current === chapters.length - 1) { auto = false; setState("ended"); }
    else if (auto) go(current + 1);
    else setState("paused");
  }

  function go(index) {
    current = index;
    resetStage();
    paintChrome();
    var t = gsap.timeline({paused: true});
    chapters[index](t);
    wait(t, HOLD);
    t.eventCallback("onUpdate", function () { gsap.set(segs[index], {scaleX: t.progress()}); });
    timeline = t;
    if (reduced && !auto) {
      // Reduced motion: show the step's finished screen instead of animating to it.
      t.progress(1);
      gsap.killTweensOf(ripple);
      gsap.set(ripple, {opacity: 0});
      gsap.set(segs[index], {scaleX: 1});
      setState(index === chapters.length - 1 ? "ended" : "paused");
    } else {
      t.eventCallback("onComplete", onChapterEnd);
      t.play();
      setState("playing");
    }
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
  next.addEventListener("click", function () { go(Math.min(chapters.length - 1, current + 1)); });
  chapterButtons.forEach(function (btn, i) {
    btn.addEventListener("click", function () {
      go(i);
      // On a phone the list sits below the stage, out of view.
      stage.scrollIntoView({behavior: reduced ? "auto" : "smooth", block: "nearest"});
    });
  });
  document.addEventListener("keydown", function (e) {
    if (e.target.closest && e.target.closest("dialog, input, textarea, select")) return;
    if (e.key === "ArrowRight" && current < chapters.length - 1) go(current + 1);
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
  go(0);
})();
