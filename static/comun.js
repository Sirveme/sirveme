// Demo Metraes · utilidades comunes: estado, tiempo real (SSE), formatos, avisos, sonido.
const Demo = (() => {
  let estado = null;
  const oyentes = [];
  const fmtS = n => "S/ " + Number(n || 0).toLocaleString("es-PE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtN = (n, d = 0) => Number(n || 0).toLocaleString("es-PE", { minimumFractionDigits: d, maximumFractionDigits: d });
  const fmtQ = (q, u) => (u === "u" ? fmtN(Math.round(q)) : fmtN(q, q < 10 ? 2 : 1)) + " " + u;
  const hora = iso => iso ? new Date(iso).toLocaleTimeString("es-PE", { timeZone: "America/Lima", hour: "2-digit", minute: "2-digit" }) : "—";
  const minDesde = iso => Math.max(0, Math.floor((Date.now() - new Date(iso)) / 60000));
  const fecha = ymd => { const [y, m, d] = ymd.split("-"); return `${d}/${m}`; };
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const metodo = m => ({ efectivo: "Efectivo", yape: "Yape/Plin", tarjeta: "Tarjeta" }[m] || "—");
  const donde = p => p.tipo === "mesa" ? `Mesa ${p.mesa}` : p.tipo === "delivery" ? `Delivery · ${p.cliente}` : "Para llevar";
  const local = id => estado?.locales.find(l => l.id == id);

  async function cargar() {
    const r = await fetch("/api/estado", { cache: "no-store" });
    const nuevo = await r.json();
    const previo = estado; estado = nuevo;
    oyentes.forEach(fn => fn(nuevo, previo));
  }

  function conectar(alEvento) {
    const vivo = document.getElementById("vivo");
    const es = new EventSource("/eventos");
    es.onopen = () => { if (vivo) { vivo.classList.add("on"); vivo.lastElementChild.textContent = "En vivo"; } cargar(); };
    es.onerror = () => { if (vivo) { vivo.classList.remove("on"); vivo.lastElementChild.textContent = "Reconectando…"; } };
    es.onmessage = async e => { const ev = JSON.parse(e.data); await cargar(); alEvento && alEvento(ev); };
  }

  function aviso(texto, tipo = "") {
    let cont = document.getElementById("avisos");
    if (!cont) { cont = document.createElement("div"); cont.id = "avisos"; cont.setAttribute("role", "status"); document.body.append(cont); }
    const el = document.createElement("div");
    el.className = "aviso " + tipo; el.textContent = texto;
    cont.prepend(el);
    setTimeout(() => el.remove(), 7000);
    while (cont.children.length > 4) cont.lastElementChild.remove();
  }

  let ctx = null;
  function activarSonido() { ctx = ctx || new (window.AudioContext || window.webkitAudioContext)(); ctx.resume(); sonar(); }
  function sonar() {
    if (!ctx) return;
    const t = ctx.currentTime;
    [880, 1175].forEach((f, i) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = f; o.type = "sine";
      g.gain.setValueAtTime(0.0001, t + i * 0.16); g.gain.exponentialRampToValueAtTime(0.25, t + i * 0.16 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + i * 0.16 + 0.15);
      o.connect(g).connect(ctx.destination); o.start(t + i * 0.16); o.stop(t + i * 0.16 + 0.16);
    });
  }
  function botonSonido(btn) {
    btn.onclick = () => { activarSonido(); btn.classList.add("pri"); btn.lastChild.textContent = " Avisos con sonido"; btn.dataset.on = "1"; };
    return () => btn.dataset.on === "1";
  }

  async function post(url, datos = {}) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(datos) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || "No se pudo completar la operación.");
    return j;
  }

  function destello(el, antes, ahora) {
    if (!el || antes === undefined || antes === null || antes === ahora) return;
    el.classList.remove("f-sube", "f-baja"); void el.offsetWidth;
    el.classList.add(ahora > antes ? "f-sube" : "f-baja");
  }

  return {
    get estado() { return estado; }, alCambiar: fn => oyentes.push(fn), cargar, conectar, aviso, post, botonSonido, sonar,
    destello, fmtS, fmtN, fmtQ, hora, minDesde, fecha, esc, metodo, donde, local,
  };
})();
