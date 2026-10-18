// Hash router: #/login and #/console (default). Everything renders into #app.

import { refresh } from "./auth.js";
import { renderLogin } from "./views/login.js";
import { renderConsole } from "./views/console.js";

const root = document.getElementById("app");
let cleanup = null;

async function route() {
  const user = await refresh();
  const hash = location.hash || "#/console";

  if (cleanup) { cleanup(); cleanup = null; }
  root.innerHTML = "";

  if (hash.startsWith("#/login")) {
    if (user) { location.hash = "#/console"; return; }
    cleanup = renderLogin(root);
  } else {
    if (!user) { location.hash = "#/login"; return; }
    cleanup = renderConsole(root, user);
  }
}

window.addEventListener("hashchange", route);
route();
