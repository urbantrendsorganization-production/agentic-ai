/*
 * Mika — UrbanTrends agent widget (P5).
 *
 * A self-contained, dependency-free embeddable. Drop one <script> onto a page
 * and Mika mounts bottom-right, isolated inside a shadow root so the host site's
 * CSS can never leak in (proposal §11 — shadow DOM isolation).
 *
 * This is the *real* widget, not the Claude Design prototype: every turn goes
 * through the actual agent loop over the HTTP API (create session → post
 * message → order form). It renders whatever the verified tool returns via
 * `action` — show_form / navigate / quote / created / kb_answer / ticket_created
 * — and maps Mika's avatar state onto the loop step (proposal §7):
 *   wait→idle · act→thinking · verify→checking · respond→talking ·
 *   navigate→pointing · order confirmed→celebrating · escalation→apologetic.
 *
 * Config via the script tag's data-* attributes:
 *   data-api-base   base URL of the agent API (default: same origin + /api)
 *   data-avatar     Mika character art URL (default: ./assets/agent1.jpg)
 *   data-auth-url   same-origin allauth session endpoint used for the identity
 *                   shortcut — greet a signed-in visitor by name without a server
 *                   round-trip (default: /_allauth/browser/v1/auth/session). The
 *                   HttpOnly sessionid cookie is sent automatically same-origin;
 *                   the widget reads only meta.is_authenticated + data.user.
 *
 * Deterministic money stays server-side: the widget never computes a price. It
 * only displays the server-authored quote and posts a plain "confirm".
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var CFG = {
    apiBase: (script && script.dataset.apiBase) || (location.origin + "/api"),
    avatar: (script && script.dataset.avatar) || "./assets/agent1.jpg",
    // Identity shortcut (MICA_INTEGRATION.md): same-origin allauth session probe.
    // Relative path so the browser auto-attaches the HttpOnly sessionid cookie.
    authUrl: (script && script.dataset.authUrl) || "/_allauth/browser/v1/auth/session",
  };

  function friendlyName(user) {
    if (!user) return "";
    if (user.display) return String(user.display);
    if (user.username) return String(user.username);
    if (user.email) return String(user.email).split("@")[0];
    return "";
  }

  // ── Design tokens (extracted from the Mika design system) ──────────────────
  var T = {
    bgBase: "#060a0c",
    bgPanel: "#0c1216",
    bgElevated: "#111a20",
    border: "rgba(255,255,255,0.08)",
    cyan: "#22d3ee",
    cyanBright: "#6ee7f4",
    cyanSoft: "rgba(34,211,238,0.12)",
    red: "#ef4444",
    text: "#e8eef1",
    textDim: "#8fa1ab",
    textFaint: "#48555e",
  };

  var STYLES =
    "@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');" +
    ":host{all:initial}" +
    "*{box-sizing:border-box;font-family:'Inter',system-ui,sans-serif}" +
    ".mono{font-family:'JetBrains Mono',monospace}" +
    ".root{position:fixed;right:20px;bottom:20px;z-index:2147483000;color:" + T.text + "}" +
    // launcher
    ".launcher{position:relative;width:96px;height:96px;border:none;background:none;cursor:pointer;padding:0;animation:mikaFloat 4s ease-in-out infinite}" +
    ".launcher .ring{position:absolute;inset:-4px;width:104px;height:104px}" +
    ".launcher .bust{width:96px;height:96px;border-radius:50%;background:" + T.bgPanel + ";border:1px solid " + T.border + ";overflow:hidden;display:flex;align-items:flex-end;justify-content:center}" +
    ".launcher:hover .bust{border-color:" + T.cyan + ";box-shadow:0 0 24px rgba(34,211,238,0.25)}" +
    ".launcher .badge{position:absolute;top:0;right:0;min-width:22px;height:22px;border-radius:9999px;background:" + T.cyan + ";color:#04181d;font:700 11px 'Inter';display:flex;align-items:center;justify-content:center;padding:0 6px;border:2px solid " + T.bgBase + "}" +
    ".bust img,.av img{width:100%;height:100%;object-fit:cover;object-position:58% 34%;transform:scale(1.15);transform-origin:58% 38%;display:block}" +
    // panel
    ".panel{width:380px;height:600px;max-height:calc(100vh - 40px);background:" + T.bgPanel + ";border:1px solid " + T.border + ";border-radius:16px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 24px 60px rgba(0,0,0,0.55);animation:mikaIn 200ms ease-out}" +
    ".hd{display:flex;align-items:center;gap:12px;padding:14px 16px;border-bottom:1px solid " + T.border + ";flex:none}" +
    ".hd .av{width:38px;height:38px;border-radius:50%;background:" + T.bgElevated + ";border:1px solid " + T.border + ";overflow:hidden;flex:none;display:flex;align-items:flex-end;justify-content:center}" +
    ".hd .name{font:600 11px 'JetBrains Mono',monospace;letter-spacing:0.12em}" +
    ".hd .name .sep{color:" + T.textFaint + "}.hd .name .role{color:" + T.cyanBright + "}" +
    ".hd .status{display:flex;align-items:center;gap:5px;margin-top:3px;font:400 10px 'JetBrains Mono',monospace;letter-spacing:0.1em;color:" + T.textDim + "}" +
    ".dot{width:5px;height:5px;border-radius:50%;background:" + T.cyan + ";flex:none}" +
    ".dot.busy{background:" + T.red + "}" +
    ".iconbtn{width:26px;height:26px;border-radius:8px;border:1px solid " + T.border + ";background:none;display:flex;align-items:center;justify-content:center;color:" + T.textDim + ";cursor:pointer}" +
    ".iconbtn:hover{color:" + T.text + ";border-color:rgba(255,255,255,0.2)}" +
    // log
    ".log{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px}" +
    ".log::-webkit-scrollbar{width:6px}.log::-webkit-scrollbar-thumb{background:" + T.bgElevated + ";border-radius:3px}" +
    ".daysep{align-self:center;font:400 10px 'JetBrains Mono',monospace;letter-spacing:0.12em;color:" + T.textFaint + "}" +
    ".row{display:flex;gap:10px;align-items:flex-end}" +
    ".row .av,.typing .av{width:26px;height:26px;border-radius:50%;background:" + T.bgElevated + ";border:1px solid " + T.border + ";overflow:hidden;flex:none;display:flex;align-items:flex-end;justify-content:center}" +
    ".bubble{max-width:260px;background:" + T.bgElevated + ";border:1px solid " + T.border + ";padding:11px 14px;font:400 13.5px/1.5 'Inter';color:" + T.text + ";white-space:pre-wrap;word-wrap:break-word}" +
    ".bubble.mika{border-radius:14px 14px 14px 4px}" +
    ".bubble.user{border-radius:14px 14px 4px 14px;max-width:250px}" +
    ".user-row{align-self:flex-end}" +
    ".chips{display:flex;flex-wrap:wrap;gap:8px;padding-left:36px}" +
    ".chip{border:1px solid rgba(34,211,238,0.4);background:" + T.cyanSoft + ";color:" + T.cyanBright + ";border-radius:9999px;padding:7px 14px;font:500 11px 'JetBrains Mono',monospace;letter-spacing:0.1em;cursor:pointer}" +
    ".chip:hover{background:rgba(34,211,238,0.22);border-color:" + T.cyan + "}" +
    ".chip.ghost{border-color:" + T.border + ";background:" + T.bgElevated + ";color:" + T.textDim + "}" +
    ".chip.ghost:hover{color:" + T.text + ";border-color:rgba(255,255,255,0.2)}" +
    // typing
    ".typing{display:flex;gap:10px;align-items:center}" +
    ".typing .box{background:" + T.bgElevated + ";border:1px solid " + T.border + ";border-radius:14px 14px 14px 4px;padding:12px 16px;display:flex;align-items:center;gap:10px}" +
    ".tdot{width:6px;height:6px;border-radius:50%;background:" + T.red + ";animation:mikaDot 1.2s infinite}" +
    ".tstatus{font:500 10px 'JetBrains Mono',monospace;letter-spacing:0.14em;color:" + T.textDim + "}" +
    // toast (navigation)
    ".toast{align-self:center;display:flex;align-items:center;gap:8px;background:" + T.cyanSoft + ";border:1px solid rgba(34,211,238,0.35);border-radius:9999px;padding:6px 14px;font:500 10px 'JetBrains Mono',monospace;letter-spacing:0.12em;color:" + T.cyanBright + "}" +
    // cards
    ".card{margin-left:36px;background:" + T.bgBase + ";border:1px solid " + T.border + ";border-radius:12px;padding:16px;display:flex;flex-direction:column;gap:13px}" +
    ".card .clabel{font:600 10.5px 'JetBrains Mono',monospace;letter-spacing:0.14em;color:" + T.cyanBright + "}" +
    ".field{display:flex;flex-direction:column;gap:6px}" +
    ".field label{font:500 10px 'JetBrains Mono',monospace;letter-spacing:0.12em;color:" + T.textDim + "}" +
    ".field input{background:" + T.bgElevated + ";border:1px solid " + T.border + ";border-radius:9px;padding:10px 12px;font:400 13px 'Inter';color:" + T.text + ";outline:none;width:100%}" +
    ".field input:focus{border-color:" + T.cyan + ";box-shadow:0 0 0 3px rgba(34,211,238,0.12)}" +
    ".opts{display:flex;flex-wrap:wrap;gap:6px}" +
    ".opt{border:1px solid " + T.border + ";background:" + T.bgElevated + ";color:" + T.textDim + ";border-radius:9999px;padding:8px 14px;font:500 10.5px 'JetBrains Mono',monospace;letter-spacing:0.1em;cursor:pointer}" +
    ".opt.sel{border-color:rgba(34,211,238,0.5);background:" + T.cyanSoft + ";color:" + T.cyanBright + "}" +
    ".btn{border:none;border-radius:10px;padding:11px 16px;font:600 12.5px 'Inter';cursor:pointer;text-align:center}" +
    ".btn.primary{background:" + T.cyan + ";color:#04181d}.btn.primary:hover{background:#4adff5}" +
    ".btn.secondary{background:" + T.bgElevated + ";border:1px solid " + T.border + ";color:" + T.textDim + "}" +
    ".btn.full{width:100%}" +
    // quote
    ".quote{margin-left:36px;background:" + T.bgBase + ";border:1px solid rgba(34,211,238,0.35);border-radius:12px;overflow:hidden}" +
    ".quote .qhd{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid " + T.border + ";background:rgba(34,211,238,0.06)}" +
    ".quote .qbody{padding:14px 16px;display:flex;flex-direction:column;gap:10px}" +
    ".qrow{display:flex;justify-content:space-between;gap:12px;font:400 12.5px 'Inter'}" +
    ".qrow .amt{color:" + T.textDim + ";font:400 11.5px 'JetBrains Mono',monospace}" +
    ".qdiv{height:1px;background:" + T.border + ";margin:2px 0}" +
    ".qtotal{display:flex;justify-content:space-between;align-items:baseline}" +
    ".qtotal .big{font:800 24px/1 'Inter';letter-spacing:-0.02em}" +
    ".qactions{padding:0 16px 14px;display:flex;gap:10px}" +
    ".qnote{padding:0 16px 12px;font:400 9.5px 'JetBrains Mono',monospace;letter-spacing:0.08em;color:" + T.textFaint + "}" +
    // confirm
    ".confirmhd{align-self:center;display:flex;align-items:center;gap:8px}" +
    ".confirmhd .lbl{font:600 12px 'JetBrains Mono',monospace;letter-spacing:0.16em;color:" + T.cyanBright + "}" +
    ".krow{display:flex;justify-content:space-between;font:400 12px 'Inter'}.krow .k{color:" + T.textDim + "}" +
    // error
    ".errbanner{margin-left:36px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.4);border-radius:12px;padding:12px 14px;display:flex;flex-direction:column;gap:8px}" +
    ".errbanner .elbl{font:600 10px 'JetBrains Mono',monospace;letter-spacing:0.14em;color:" + T.red + "}" +
    ".errbanner .etxt{font:400 12px/1.5 'Inter';color:" + T.text + "}" +
    // input bar
    ".bar{padding:12px 14px;border-top:1px solid " + T.border + ";display:flex;gap:10px;align-items:center;flex:none}" +
    ".bar input{flex:1;background:" + T.bgElevated + ";border:1px solid " + T.border + ";border-radius:10px;padding:11px 14px;font:400 13px 'Inter';color:" + T.text + ";outline:none;min-width:0}" +
    ".bar input:focus{border-color:" + T.cyan + ";box-shadow:0 0 0 3px rgba(34,211,238,0.12)}" +
    ".send{width:40px;height:40px;border-radius:10px;background:" + T.cyan + ";border:none;display:flex;align-items:center;justify-content:center;flex:none;cursor:pointer}" +
    ".send:hover{background:#4adff5}" +
    // animations
    "@keyframes mikaDot{0%,80%,100%{opacity:0.25;transform:scale(0.85)}40%{opacity:1;transform:scale(1)}}" +
    "@keyframes mikaFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}" +
    "@keyframes ringPulse{0%,100%{opacity:0.9}50%{opacity:0.4}}" +
    "@keyframes mikaIn{from{opacity:0;transform:translateY(8px) scale(0.98)}to{opacity:1;transform:none}}" +
    "@keyframes rowIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}" +
    ".log>*{animation:rowIn 180ms ease-out}" +
    "@media (max-width:480px){.root{right:0;bottom:0;left:0}.panel{width:100vw;height:80vh;border-radius:20px 20px 0 0}}" +
    "@media (prefers-reduced-motion:reduce){*{animation:none !important;transition:none !important}}";

  // Mika's status ring (red segment) — the signature the design uses everywhere.
  var RING =
    '<svg class="ring" viewBox="0 0 100 100"><circle cx="50" cy="50" r="48" fill="none" ' +
    'stroke="' + T.red + '" stroke-width="2" stroke-dasharray="86 216" stroke-dashoffset="-46" ' +
    'stroke-linecap="round" opacity="0.9"/></svg>';
  var SEND_ICON =
    '<svg width="15" height="15" viewBox="0 0 16 16"><path d="M2 8 L14 2 L10 14 L7.5 8.5 Z" fill="#04181d"/></svg>';
  var CHECK_ICON =
    '<svg width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7.5" fill="rgba(34,211,238,0.12)" stroke="' + T.cyan + '"/>' +
    '<path d="M4.5 8.2 L7 10.5 L11.5 5.5" stroke="' + T.cyan + '" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function avatarHTML() {
    return '<div class="av"><img src="' + esc(CFG.avatar) + '" alt="Mika" draggable="false"></div>';
  }

  // ── persistence: survive full-page navigations (the /login round-trip) ───────
  // Mika deep-links anonymous visitors to /login mid-order. Without persisting the
  // session, the page reload would start a brand-new chat AND abandon the
  // server-side order draft — so the visitor signs in, comes back, and Mika has
  // forgotten the quote. We stash the session id + a short transcript in
  // localStorage (TTL-bounded so we never resurrect a stale conversation).
  var STORE_KEY = "mika.state.v1";
  var STORE_TTL = 6 * 60 * 60 * 1000; // 6h
  function loadState() {
    try {
      var s = JSON.parse(window.localStorage.getItem(STORE_KEY) || "null");
      if (!s || !s.sid || Date.now() - (s.ts || 0) > STORE_TTL) {
        window.localStorage.removeItem(STORE_KEY);
        return null;
      }
      return s;
    } catch (e) { return null; }
  }
  function saveState(s) {
    try {
      s.ts = Date.now();
      window.localStorage.setItem(STORE_KEY, JSON.stringify(s));
    } catch (e) { /* private mode / disabled — degrade to in-memory only */ }
  }

  function Widget() {
    var st = loadState();
    this.sessionId = st ? st.sid : null;
    this.history = st && st.log ? st.log : []; // [{r:"u"|"m", t}] replayed on open
    this.wasOpen = !!(st && st.open);          // reopen after a login round-trip
    this.draft = null; // active order draft form context {service}
    this.open = false;
    this.busy = false;
    this.unread = 0;
    this._build();
  }

  Widget.prototype._persist = function () {
    if (!this.sessionId) return; // nothing to resume until a session exists
    saveState({ sid: this.sessionId, log: this.history.slice(-60), open: this.open });
  };
  Widget.prototype._pushHistory = function (r, t) {
    this.history.push({ r: r, t: t });
    if (this.history.length > 60) this.history = this.history.slice(-60);
    this._persist();
  };

  Widget.prototype._build = function () {
    this.host = el("div");
    this.host.style.cssText = "position:fixed;right:0;bottom:0;z-index:2147483000";
    this.shadow = this.host.attachShadow({ mode: "open" });
    var style = document.createElement("style");
    style.textContent = STYLES;
    this.shadow.appendChild(style);
    this.root = el("div", "root");
    this.shadow.appendChild(this.root);
    document.body.appendChild(this.host);
    this._renderLauncher();
  };

  Widget.prototype._renderLauncher = function () {
    this.open = false;
    this.root.innerHTML = "";
    var b = el("button", "launcher");
    b.setAttribute("aria-label", "Chat with Mika, the UrbanTrends agent");
    b.innerHTML =
      RING +
      '<div class="bust">' +
      '<img src="' + esc(CFG.avatar) + '" alt="Mika" draggable="false">' +
      "</div>" +
      (this.unread ? '<span class="badge">' + this.unread + "</span>" : "");
    var self = this;
    b.addEventListener("click", function () {
      self._openPanel();
    });
    this.root.appendChild(b);
  };

  Widget.prototype._openPanel = function () {
    this.open = true;
    this.unread = 0;
    this.root.innerHTML = "";
    var self = this;

    var panel = el("div", "panel");
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Mika — UrbanTrends agent");

    // header
    var hd = el("div", "hd");
    hd.innerHTML =
      avatarHTML() +
      '<div style="flex:1;min-width:0">' +
      '<div class="name">MIKA <span class="sep">/</span> <span class="role">URBANTRENDS AGENT</span></div>' +
      '<div class="status"><span class="sdot dot"></span><span class="slabel">ONLINE</span></div>' +
      "</div>";
    var min = el("button", "iconbtn", '<svg width="10" height="10" viewBox="0 0 10 10"><path d="M1 5 h8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>');
    min.setAttribute("aria-label", "Minimize");
    min.addEventListener("click", function () {
      self.open = false;
      self._persist();
      self._renderLauncher();
    });
    var actions = el("div"); actions.style.cssText = "display:flex;gap:6px";
    actions.appendChild(min);
    hd.appendChild(actions);

    // log
    this.logEl = el("div", "log");
    this.logEl.setAttribute("role", "log");
    this.logEl.setAttribute("aria-live", "polite");
    this.logEl.appendChild(el("div", "daysep", "TODAY"));

    // input bar
    var bar = el("div", "bar");
    this.input = el("input");
    this.input.placeholder = "Message Mika…";
    this.input.setAttribute("aria-label", "Message Mika");
    this.input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") self._onSend();
    });
    var send = el("button", "send", SEND_ICON);
    send.setAttribute("aria-label", "Send");
    send.addEventListener("click", function () { self._onSend(); });
    bar.appendChild(this.input);
    bar.appendChild(send);

    panel.appendChild(hd);
    panel.appendChild(this.logEl);
    panel.appendChild(bar);
    this.root.appendChild(panel);

    this.headerDot = this.shadow.querySelector(".sdot");
    this.headerLabel = this.shadow.querySelector(".slabel");

    if (this.history && this.history.length) {
      // Returning visitor (e.g. back from the /login redirect): replay the
      // transcript so the conversation picks up exactly where it left off.
      this._greeted = true;
      var self3 = this;
      this.history.forEach(function (m) {
        if (m.r === "u") self3._user(m.t, true); else self3._mika(m.t, true);
      });
    } else if (!this._greeted) {
      this._greeted = true;
      var self4 = this;
      // Identity shortcut: greet a signed-in visitor by name, else generically.
      this._checkAuth().then(function (user) {
        var name = friendlyName(user);
        if (self4.authed && name) {
          self4._mika(
            "Karibu back, " + name + "! I can get you a quote, set you up on an " +
              "UrbanTrends service, point you around the site, or answer a quick " +
              "question — what can I do for you?"
          );
        } else {
          self4._mika(
            "Karibu! I'm Mika. I can get you a quote, set you up on an UrbanTrends " +
              "service, point you around the site, or answer a quick question — what " +
              "brings you in?"
          );
        }
        self4._chips([
          { label: "ORDER A LANDING PAGE", text: "I'd like to order a landing page" },
          { label: "HOW DOES PAYMENT WORK?", text: "What payment methods do you accept?" },
          { label: "TALK TO A HUMAN", text: "I'd like to talk to a human", ghost: true },
        ]);
      });
    }
    this._persist(); // remember the panel is open so we reopen after a page nav
    this.input.focus();
  };

  // ── avatar / loop state (proposal §7) ──────────────────────────────────────
  Widget.prototype._setState = function (state) {
    if (!this.headerDot) return;
    var map = {
      idle: ["ONLINE", false],
      thinking: ["THINKING…", true],
      checking: ["VERIFYING…", true],
      talking: ["ONLINE", false],
      pointing: ["NAVIGATING…", false],
      celebrating: ["ONLINE", false],
      apologetic: ["DEGRADED", true],
    };
    var m = map[state] || map.idle;
    this.headerLabel.textContent = m[0];
    this.headerDot.classList.toggle("busy", !!m[1]);
    this.host.dataset.mika = state; // hook for future sprite/Lottie swap
  };

  // ── render helpers ─────────────────────────────────────────────────────────
  Widget.prototype._scroll = function () {
    var l = this.logEl;
    if (l) l.scrollTop = l.scrollHeight;
  };
  Widget.prototype._append = function (node) {
    this.logEl.appendChild(node);
    this._scroll();
    return node;
  };
  Widget.prototype._mika = function (text, replay) {
    var row = el("div", "row");
    row.innerHTML = avatarHTML() + '<div class="bubble mika">' + esc(text) + "</div>";
    if (!replay) this._pushHistory("m", text);
    return this._append(row);
  };
  Widget.prototype._user = function (text, replay) {
    var row = el("div", "row user-row");
    row.innerHTML = '<div class="bubble user">' + esc(text) + "</div>";
    if (!replay) this._pushHistory("u", text);
    return this._append(row);
  };
  Widget.prototype._chips = function (chips) {
    var self = this;
    var wrap = el("div", "chips");
    chips.forEach(function (c) {
      var chip = el("button", "chip" + (c.ghost ? " ghost" : ""), esc(c.label));
      chip.addEventListener("click", function () {
        wrap.remove();
        self._send(c.text || c.label);
      });
      wrap.appendChild(chip);
    });
    return this._append(wrap);
  };
  Widget.prototype._typing = function (status) {
    var row = el("div", "typing");
    row.innerHTML =
      avatarHTML() +
      '<div class="box"><div style="display:flex;gap:4px">' +
      '<span class="tdot"></span><span class="tdot" style="animation-delay:.2s"></span><span class="tdot" style="animation-delay:.4s"></span>' +
      '</div><span class="tstatus">' + esc(status || "THINKING…") + "</span></div>";
    this._typingEl = this._append(row);
    return this._typingEl;
  };
  Widget.prototype._clearTyping = function () {
    if (this._typingEl) { this._typingEl.remove(); this._typingEl = null; }
  };

  // ── networking ─────────────────────────────────────────────────────────────
  Widget.prototype._api = function (path, body) {
    return fetch(CFG.apiBase + path, {
      method: "POST",
      // Same-origin (through the urbantrends.dev proxy): send the httpOnly
      // `sessionid` cookie so the agent can verify the visitor's host login.
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  };
  Widget.prototype._ensureSession = function () {
    var self = this;
    if (this.sessionId) return Promise.resolve(this.sessionId);
    return this._api("/sessions/", {}).then(function (s) {
      self.sessionId = s.id;
      self._persist();
      return s.id;
    });
  };

  // Identity shortcut (MICA_INTEGRATION.md): ask allauth directly, same-origin, so
  // the HttpOnly sessionid cookie rides along and we can greet a signed-in visitor
  // by name with no server round-trip. Read-only; anonymous (or any error) → null.
  // Write / user-scoped actions still authenticate server-side via X-UT-Session.
  Widget.prototype._checkAuth = function () {
    var self = this;
    if (this._authChecked) return Promise.resolve(this.user);
    return fetch(CFG.authUrl, {
      method: "GET",
      credentials: "include",
      headers: { Accept: "application/json" },
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (p) {
        var authed = !!(p && p.meta && p.meta.is_authenticated);
        self.authed = authed;
        self.user = authed ? (p.data && p.data.user) || null : null;
        self._authChecked = true;
        return self.user;
      })
      .catch(function () {
        self.authed = false; self.user = null; self._authChecked = true; return null;
      });
  };

  Widget.prototype._onSend = function () {
    var t = (this.input.value || "").trim();
    if (!t) return;
    this.input.value = "";
    this._send(t);
  };

  Widget.prototype._send = function (text) {
    if (this.busy) return;
    var self = this;
    this._user(text);
    this.busy = true;
    this._setState("thinking");
    this._typing("THINKING…");
    this._ensureSession()
      .then(function (id) {
        return self._api("/sessions/" + id + "/messages/", { text: text });
      })
      .then(function (res) { self._handle(res); })
      .catch(function () { self._netError(); })
      .then(function () { self.busy = false; });
  };

  // ── outcome routing: render whatever the verified tool returned ────────────
  Widget.prototype._handle = function (res) {
    this._clearTyping();
    var action = res && res.action;

    // Escalation / handoff → apologetic + ticket banner.
    if (res.escalated || (action && action.action === "ticket_created")) {
      this._setState("apologetic");
      if (res.reply) this._mika(res.reply);
      if (action && action.ticket_ref) this._ticketBanner(action.ticket_ref);
      return;
    }

    if (action && action.action === "show_form") {
      if (res.reply) this._mika(res.reply);
      this._setState("talking");
      this._formCard(action.form);
      return;
    }
    if (action && action.action === "quote") {
      if (res.reply) this._mika(res.reply);
      this._setState("talking");
      this._quoteCard(action.quote);
      return;
    }
    if (action && action.created === true) {
      this._setState("celebrating");
      if (res.reply) this._mika(res.reply);
      this._confirmCard(action);
      return;
    }
    if (action && action.action === "navigate") {
      this._setState("pointing");
      var dest = String(action.path || "");
      this._toast("TAKING YOU TO " + dest.toUpperCase());
      if (res.reply) this._mika(res.reply);
      // Actually take the visitor there. The widget is same-origin on the host
      // site, so a relative path navigates the top-level page (e.g. /login).
      // Append ?next=<here> so the login flow returns the visitor to this page —
      // the session is persisted, so Mika reopens with the conversation + quote
      // intact and they can just confirm again. Brief delay so the toast + reply
      // are readable before the page unloads.
      if (dest) {
        var back = window.location.pathname + window.location.search;
        var url = dest + (dest.indexOf("?") === -1 ? "?" : "&") +
          "next=" + encodeURIComponent(back);
        setTimeout(function () { window.location.assign(url); }, 1600);
      }
      return;
    }

    // Plain reply (kb_answer, echo, login prompts, created:false, …).
    this._setState("talking");
    if (res.reply) this._mika(res.reply);
  };

  Widget.prototype._netError = function () {
    this._clearTyping();
    this._setState("apologetic");
    this._mika("Pole sana — I couldn't reach the service just now. Give it another go in a moment.");
  };

  // ── cards ──────────────────────────────────────────────────────────────────
  Widget.prototype._formCard = function (form) {
    var self = this;
    this.draft = { service: form.service };
    var values = {};
    var card = el("div", "card");
    card.appendChild(el("div", "clabel", esc((form.title || "DETAILS").toUpperCase())));

    (form.fields || []).forEach(function (f) {
      if (f.default !== undefined) values[f.name] = f.default;
      var field = el("div", "field");
      field.appendChild(el("label", null, esc((f.label || f.name).toUpperCase())));

      if (f.type === "boolean") {
        var opts = el("div", "opts");
        [["Yes", true], ["No", false]].forEach(function (o) {
          var btn = el("button", "opt" + (values[f.name] === o[1] ? " sel" : ""), o[0]);
          btn.addEventListener("click", function () {
            values[f.name] = o[1];
            opts.querySelectorAll(".opt").forEach(function (x) { x.classList.remove("sel"); });
            btn.classList.add("sel");
          });
          opts.appendChild(btn);
        });
        field.appendChild(opts);
      } else if (f.type === "enum") {
        var wrap = el("div", "opts");
        (f.options || []).forEach(function (o) {
          var btn = el("button", "opt" + (values[f.name] === o ? " sel" : ""), esc(o));
          btn.addEventListener("click", function () {
            values[f.name] = o;
            wrap.querySelectorAll(".opt").forEach(function (x) { x.classList.remove("sel"); });
            btn.classList.add("sel");
          });
          wrap.appendChild(btn);
        });
        field.appendChild(wrap);
      } else {
        var input = el("input");
        input.type = f.type === "integer" ? "number" : "text";
        if (f.type === "integer") input.inputMode = "numeric";
        if (f.min !== undefined) input.min = f.min;
        if (f.max !== undefined) input.max = f.max;
        if (f.default !== undefined) input.value = f.default;
        input.placeholder = f.placeholder || "";
        input.addEventListener("input", function () {
          values[f.name] = f.type === "integer" ? parseInt(input.value, 10) : input.value;
        });
        field.appendChild(input);
      }
      card.appendChild(field);
    });

    var submit = el("button", "btn primary full", "Continue →");
    submit.addEventListener("click", function () {
      submit.disabled = true;
      card.style.opacity = "0.5";
      self._submitForm(values, card);
    });
    card.appendChild(submit);
    this._append(card);
  };

  Widget.prototype._submitForm = function (values, card) {
    var self = this;
    this.busy = true;
    this._setState("checking");
    this._typing("PRICING…");
    this._api("/sessions/" + this.sessionId + "/order/form/", values)
      .then(function (res) {
        card.remove(); // replace the form with its result
        self._handle(res);
      })
      .catch(function (e) {
        card.style.opacity = "1";
        self._clearTyping();
        self._setState("apologetic");
        self._mika("That didn't go through — please check the details and try again.");
      })
      .then(function () { self.busy = false; });
  };

  Widget.prototype._quoteCard = function (quote) {
    var self = this;
    var q = el("div", "quote");
    var items = (quote.breakdown || [])
      .map(function (it) {
        return (
          '<div class="qrow"><span>' + esc(it.label) + "</span>" +
          '<span class="amt">' + esc(fmt(it.amount)) + "</span></div>"
        );
      })
      .join("");
    q.innerHTML =
      '<div class="qhd"><span class="clabel">SYSTEM / QUOTE</span>' +
      '<span class="mono" style="font-size:10px;color:' + T.textDim + '">' + esc(quote.currency) + "</span></div>" +
      '<div class="qbody">' + items +
      '<div class="qdiv"></div><div class="qtotal">' +
      '<span class="mono" style="font-size:10px;letter-spacing:0.14em;color:' + T.textDim + '">TOTAL</span>' +
      '<span class="big">' + esc(quote.currency) + " " + esc(fmt(quote.amount)) + "</span></div></div>";
    var actions = el("div", "qactions");
    var confirm = el("button", "btn primary", "Confirm order →");
    confirm.style.flex = "1";
    confirm.addEventListener("click", function () {
      actions.remove();
      note.remove();
      self._send("confirm");
    });
    var adjust = el("button", "btn secondary", "Adjust");
    adjust.addEventListener("click", function () {
      actions.remove();
      note.remove();
      self._mika("Sure — tell me what to change and I'll re-price it.");
      self.input.focus();
    });
    actions.appendChild(confirm);
    actions.appendChild(adjust);
    var note = el("div", "qnote", "GENERATED BY THE PRICING ENGINE · SERVER-COMPUTED");
    q.appendChild(actions);
    q.appendChild(note);
    this._append(q);
  };

  Widget.prototype._confirmCard = function (action) {
    var head = el("div", "confirmhd", CHECK_ICON + '<span class="lbl">ORDER CONFIRMED</span>');
    this._append(head);
    var ref = String(action.order_id || "").slice(0, 8).toUpperCase();
    var card = el("div", "card");
    card.style.marginLeft = "0";
    card.innerHTML =
      '<div class="krow"><span class="k">Order ref</span><span class="mono" style="font-size:11.5px">' + esc(ref) + "</span></div>" +
      '<div class="krow"><span class="k">Status</span><span style="color:' + T.cyanBright + '">' + esc((action.status || "pending").toUpperCase()) + "</span></div>";
    this._append(card);
  };

  Widget.prototype._toast = function (text) {
    this._append(el("div", "toast", '<span style="color:' + T.cyan + '">→</span> ' + esc(text)));
  };

  Widget.prototype._ticketBanner = function (ref) {
    var b = el("div", "errbanner");
    b.innerHTML =
      '<span class="elbl">SYSTEM / TICKET ' + esc(ref) + "</span>" +
      '<span class="etxt">A human on the UrbanTrends team has this, with the conversation attached. They\'ll follow up shortly.</span>';
    this._append(b);
  };

  function fmt(amount) {
    var n = Number(amount);
    if (!isFinite(n)) return String(amount);
    return n.toLocaleString("en-KE");
  }

  function boot() {
    if (window.__mikaWidget) return;
    var w = new Widget();
    window.__mikaWidget = w;
    // Reopen automatically after a full-page navigation (e.g. returning from the
    // /login redirect) so the visitor lands back in their conversation.
    if (w.wasOpen) w._openPanel();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
