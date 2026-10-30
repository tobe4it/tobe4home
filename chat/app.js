"use strict";
(() => {
  const messages = document.getElementById("messages");
  const form = document.getElementById("chat-form");
  const prompt = document.getElementById("prompt");
  const send = document.getElementById("send");
  const state = document.getElementById("state");
  const counter = document.getElementById("counter");
  let csrf = "";
  let ready = false;
  let busy = false;
  let history = [];
  function line(role, content) {
    const item = document.createElement("article");
    item.className = "message " + role;
    const head = document.createElement("strong");
    head.textContent = role === "user" ? "Du" : "tobe4home";
    const text = document.createElement("p");
    text.textContent = content; // Never render LLM-generated HTML/Markdown as HTML.
    item.append(head, text);
    messages.appendChild(item);
    item.scrollIntoView({behavior:"smooth",block:"end"});
  }
  function buttons() {
    send.disabled = !ready || busy || !prompt.value.trim();
    counter.textContent = prompt.value.length + " / 1600";
  }
  prompt.addEventListener("input", buttons);
  prompt.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      if (!send.disabled) form.requestSubmit();
    }
  });
  async function connect() {
    try {
      const response = await fetch("/api/status", {cache:"no-store"});
      if (!response.ok) throw new Error("Server antwortet nicht");
      const info = await response.json();
      csrf = info.csrf;
      ready = Boolean(info.configured);
      state.textContent = ready
        ? "● Modell: " + info.model + " · Nur Beratung, keine Ausführung"
        : "● Modell noch nicht konfiguriert – in CT1001 /etc/tobe4home/chat.json setzen";
    } catch {
      ready = false;
      state.textContent = "● Chatdienst nicht erreichbar";
    }
    buttons();
  }
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!ready || busy || !prompt.value.trim()) return;
    busy = true;
    const content = prompt.value.trim();
    prompt.value = "";
    line("user", content);
    const request = [...history.slice(-8), {role:"user",content}];
    buttons();
    try {
      const response = await fetch("/api/chat", {
        method:"POST",
        headers:{"Content-Type":"application/json","X-TB4H-CSRF":csrf},
        body:JSON.stringify({messages:request})
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "LLM-Anfrage fehlgeschlagen");
      line("assistant", result.reply);
      history = [...request, {role:"assistant",content:result.reply}].slice(-8);
    } catch(err) {
      line("assistant", "Keine Änderung ausgeführt. " + (err.message || "LLM-Endpunkt nicht verfügbar"));
      history = request.slice(-8);
    } finally {
      busy = false;
      buttons();
    }
  });
  connect();
})();
