// Sign-in / create-account view. Demo credentials are surfaced on purpose —
// this is a hackathon submission and judges get a working login on arrival.

import { api } from "../api.js";
import { login, register } from "../auth.js";

const LOGO = `<svg width="34" height="34" viewBox="0 0 28 28" fill="none" aria-hidden="true">
  <circle cx="12" cy="12" r="7.2" stroke="#e3b34c" stroke-width="1.7"/>
  <path d="M17.2 17.2 L23.4 23.4" stroke="#e3b34c" stroke-width="2.4" stroke-linecap="round"/>
  <circle cx="9.5" cy="10" r="1.5" fill="#e3b34c"/><circle cx="14.6" cy="11.4" r="1.5" fill="#e3b34c"/>
  <circle cx="11" cy="14.6" r="1.5" fill="#e3b34c"/>
  <path d="M9.5 10 L14.6 11.4 L11 14.6 Z" stroke="#e3b34c" stroke-width="1" opacity=".55"/></svg>`;

export function renderLogin(root) {
  root.innerHTML = `
  <div class="auth-wrap">
    <div class="auth-brand">
      <div class="logo-line">${LOGO}<span class="word">Ledger<i>Lens</i></span></div>
      <div class="sub">The fraud-ring investigator where one FalkorDB graph per bank is the
        entire context layer — data, memory, SOPs and audit trail.</div>
    </div>
    <div class="auth-card" role="main">
      <div class="auth-tabs" id="auth-tabs">
        <button class="auth-tab on" id="tab-in" type="button">Sign in</button>
        <button class="auth-tab" id="tab-up" type="button">Create account</button>
      </div>

      <form id="form-in" novalidate>
        <div class="field"><label for="in-user">Username</label>
          <input id="in-user" autocomplete="username" required></div>
        <div class="field"><label for="in-pass">Password</label>
          <input id="in-pass" type="password" autocomplete="current-password" required></div>
        <div class="auth-err" id="err-in"></div>
        <button class="btn btn-block" id="go-in" type="submit">Sign in</button>
      </form>

      <form id="form-up" hidden novalidate>
        <div class="field"><label for="up-name">Full name</label>
          <input id="up-name" autocomplete="name" required></div>
        <div class="field"><label for="up-user">Username</label>
          <input id="up-user" autocomplete="username" required></div>
        <div class="field"><label for="up-pass">Password (min 8 chars)</label>
          <input id="up-pass" type="password" autocomplete="new-password" required></div>
        <div class="field"><label for="up-tenant">Bank (tenant)</label>
          <select id="up-tenant" required></select></div>
        <div class="auth-err" id="err-up"></div>
        <button class="btn btn-block" id="go-up" type="submit">Create account</button>
      </form>

      <div class="auth-note">
        Demo logins — analyst <code>analyst@aurora</code> ·
        admin <code>admin@ledgerlens.io</code> · password <code>ledgerlens123</code>.
        Each analyst sees only their bank; admins can switch tenants.
      </div>
    </div>
  </div>`;

  const $ = (id) => root.querySelector(`#${id}`);
  const tabIn = $("tab-in"), tabUp = $("tab-up");
  const formIn = $("form-in"), formUp = $("form-up");

  function show(which) {
    const isIn = which === "in";
    tabIn.classList.toggle("on", isIn); tabUp.classList.toggle("on", !isIn);
    formIn.hidden = !isIn; formUp.hidden = isIn;
    $("err-in").textContent = ""; $("err-up").textContent = "";
  }
  tabIn.onclick = () => show("in");
  tabUp.onclick = () => show("up");

  // Prefill the demo analyst so the first sign-in is one click.
  $("in-user").value = "analyst@aurora";
  $("in-pass").value = "ledgerlens123";

  formIn.onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("go-in");
    btn.disabled = true; btn.textContent = "Signing in…";
    try {
      await login($("in-user").value.trim(), $("in-pass").value);
      location.hash = "#/console";
    } catch (err) {
      $("err-in").textContent = err.message;
      btn.disabled = false; btn.textContent = "Sign in";
    }
  };

  formUp.onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("go-up");
    btn.disabled = true; btn.textContent = "Creating…";
    try {
      await register({
        full_name: $("up-name").value.trim(),
        username: $("up-user").value.trim(),
        password: $("up-pass").value,
        tenant: $("up-tenant").value,
      });
      location.hash = "#/console";
    } catch (err) {
      $("err-up").textContent = err.message;
      btn.disabled = false; btn.textContent = "Create account";
    }
  };

  // Tenant options for the register form (open endpoint by design).
  api("/api/tenants").then((r) => {
    $("up-tenant").innerHTML = (r.tenants || [])
      .map((t) => `<option value="${t}">${t}</option>`).join("");
  }).catch(() => { $("up-tenant").innerHTML = "<option>unavailable</option>"; });

  return () => {}; // nothing to tear down
}
