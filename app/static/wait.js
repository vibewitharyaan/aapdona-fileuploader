const token = location.pathname.split("/").pop();
const nameEl = document.getElementById("name");
const progress = document.getElementById("progress");
const fill = document.getElementById("fill");
const pct = document.getElementById("pct");
const statusEl = document.getElementById("status");

let last = null;

function fmtBytes(n) {
  if (n >= 1024 ** 3) return (n / 1024 ** 3).toFixed(2) + " GB";
  if (n >= 1024 ** 2) return (n / 1024 ** 2).toFixed(1) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(0) + " KB";
  return n + " B";
}

function fmtTime(s) {
  if (s < 60) return Math.round(s) + "s";
  if (s < 3600) return Math.floor(s / 60) + "m " + Math.round(s % 60) + "s";
  return (s / 3600).toFixed(1) + "h";
}

async function tick() {
  try {
    const r = await fetch("/f/" + token + "?info=1");
    const j = await r.json();
    if (j.status !== "uploading") {
      location.href = location.pathname + "?dl=1";
      return;
    }
    nameEl.textContent = j.name;
    const written = j.written;
    const total = j.total;
    const p = total ? Math.round((written / total) * 100) : 0;
    fill.style.width = p + "%";
    progress.textContent = fmtBytes(written) + " / " + fmtBytes(total) + " (" + p + "%)";
    const now = Date.now();
    let msg = "a little more…";
    if (last && j.written > last.written) {
      const dt = (now - last.t) / 1000;
      const rate = (j.written - last.written) / dt;
      const left = Math.max(total - written, 0) / Math.max(rate, 1);
      msg = "~" + fmtTime(left) + " left (live estimate)";
    }
    pct.textContent = "remaining: " + fmtBytes(Math.max(total - written, 0)) + " · " + msg;
    last = { written: j.written, t: now };
  } catch (_) {
    statusEl.textContent = "can't reach the server…";
  }
}

tick();
setInterval(tick, 1000);