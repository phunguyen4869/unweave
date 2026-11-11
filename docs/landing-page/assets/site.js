/* Shared by every page: language switch and the coffee dialog.
   A page sets window.SITE_TRANSLATIONS before loading this file. */
(function () {
  var COMMON_VI = {
      "nav.home": "Trang chủ",
      "nav.guide": "Hướng dẫn",
      "footer.p1": "Giấy phép MIT. Thực hiện bởi <a href=\"https://github.com/um1chc5\">um1chc5</a>, dựa trên <a href=\"https://github.com/pedromtcosta/sound-razor\">Sound Razor</a> của pedromtcosta.",
      "footer.p2": "<a href=\"https://github.com/um1chc5/unweave\">Mã nguồn trên GitHub</a> · <a href=\"https://www.facebook.com/um1chc5/\">Facebook</a> · <a href=\"https://github.com/um1chc5/unweave/releases\">Tất cả bản phát hành</a> · <a href=\"https://github.com/um1chc5/unweave/issues\">Báo lỗi</a>",
      "coffee.btn": "Mời tôi ly cà phê",
      "coffee.btnShort": "Cà phê",
      "coffee.title": "Mời tôi ly cà phê",
      "coffee.lead": "Nếu Unweave hữu ích với bạn, một ly cà phê giúp dự án tiếp tục. Cảm ơn bạn.",
      "coffee.hint": "Quét bằng app ngân hàng (VietQR / Napas 247)",
      "coffee.account": "TK",
      "coffee.close": "Đóng"
  };
  var page = (window.SITE_TRANSLATIONS && window.SITE_TRANSLATIONS.vi) || {};
  var vi = Object.assign({}, COMMON_VI, page);

  var original = {};
  document.querySelectorAll("[data-i18n]").forEach(function (el) {
    original[el.getAttribute("data-i18n")] = el.innerHTML;
  });

  function applyLang(lang) {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      var key = el.getAttribute("data-i18n");
      el.innerHTML = lang === "vi" ? (vi[key] || original[key]) : original[key];
    });
    document.querySelectorAll(".lang-toggle button").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-lang") === lang);
    });
    try { localStorage.setItem("srLang", lang); } catch (_) {}
    document.dispatchEvent(new CustomEvent("site:lang", {detail: lang}));
  }

  document.querySelectorAll(".lang-toggle button").forEach(function (btn) {
    btn.addEventListener("click", function () {
      applyLang(btn.getAttribute("data-lang"));
    });
  });

  var saved = null;
  try { saved = localStorage.getItem("srLang"); } catch (_) {}
  applyLang(saved || (navigator.language && navigator.language.toLowerCase().indexOf("vi") === 0 ? "vi" : "en"));

  var dialog = document.getElementById("coffee-dialog");
  var openBtn = document.getElementById("coffee-open");
  var closeBtn = document.getElementById("coffee-close");
  if (dialog && openBtn && closeBtn && typeof dialog.showModal === "function") {
    openBtn.addEventListener("click", function () { dialog.showModal(); });
    closeBtn.addEventListener("click", function () { dialog.close(); });
    dialog.addEventListener("click", function (e) {
      if (e.target === dialog) dialog.close();
    });
  }
})();
