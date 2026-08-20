const drop = document.getElementById("drop");
const file = document.getElementById("file");
const pick = document.getElementById("pick");
const banner = document.getElementById("banner");
const key = document.getElementById("key");
const life = document.getElementById("life");
const nameEl = document.getElementById("name");
const bar = document.getElementById("bar");
const fill = document.getElementById("fill");
const pct = document.getElementById("pct");
const done = document.getElementById("done");
const fname = document.getElementById("fname");
const url = document.getElementById("url");
const copy = document.getElementById("copy");
const cancel = document.getElementById("cancel");
const gauge = document.getElementById("gauge");
const gstat = document.getElementById("gstat");
const toast = document.getElementById("toast");

let toastTimer;

function popToast(msg) {
  toast.textContent = msg;
  show(toast, true);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => show(toast, false), 3000);
}

let lifetime = "30m";
let current = null;

function fmtBytes(n) {
  if (n >= 1024 ** 3) return (n / 1024 ** 3).toFixed(2) + " GB";
  if (n >= 1024 ** 2) return (n / 1024 ** 2).toFixed(1) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(0) + " KB";
  return n + " B";
}

function loadStatus() {
  fetch("/status")
    .then((r) => r.json())
    .then((j) => {
      const segs = 8;
      const filled = Math.round((j.bytes / Math.max(j.cap, 1)) * segs);
      gauge.innerHTML = "";
      for (let i = 0; i < segs; i++) {
        const s = document.createElement("i");
        s.className = "seg" + (i < filled ? (i < segs - 2 ? "" : " hot") : " empty");
        gauge.appendChild(s);
      }
      const used = Math.round((j.bytes / Math.max(j.cap, 1)) * 100);
      gstat.textContent = fmtBytes(j.bytes) + " of " + fmtBytes(j.cap) + " filled (" + used + "%)";
    })
    .catch(() => {
      gstat.textContent = "storage gauge is napping…";
    });
}
loadStatus();

function show(id, on) {
  id.classList.toggle("hidden", !on);
}

life.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-life]");
  if (!btn) return;
  lifetime = btn.dataset.life;
  life.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === btn));
});

function fmtTime(s) {
  if (s < 60) return Math.round(s) + "s";
  if (s < 3600) return Math.round(s / 60) + "m";
  return (s / 3600).toFixed(1) + "h";
}

function setLocked(locked) {
  drop.classList.toggle("disabled", locked);
  pick.disabled = locked;
}

let authTimer;
key.addEventListener("input", () => {
  setLocked(true);
  clearTimeout(authTimer);
  authTimer = setTimeout(checkKey, 300);
});

function checkKey() {
  const pw = key.value.trim();
  if (!pw) return setLocked(true);
  fetch("/auth", { headers: { "X-Upload-Key": pw } })
    .then((r) => {
      setLocked(r.status !== 200);
      if (!r.ok) {
        banner.textContent = "wrong key";
        show(banner, true);
      } else {
        show(banner, false);
      }
    })
    .catch(() => setLocked(true));
}
checkKey();

function start(fileObj) {
  const pw = key.value.trim();
  if (!pw) {
    banner.textContent = "Enter the upload key first.";
    show(banner, true);
    return;
  }
  show(banner, false);
  setLocked(true);
  nameEl.textContent = fileObj.name;
  fill.style.width = "0%";
  pct.textContent = "0%";
  show(bar, true);
  show(pct, true);
  show(done, false);
  show(cancel, true);

  const size = fileObj.size || 0;
  const prep = new XMLHttpRequest();
  current = prep;
  prep.open("POST", "/upload/prepare?name=" + encodeURIComponent(fileObj.name) + "&lifetime=" + lifetime + "&size=" + size);
  prep.setRequestHeader("X-Upload-Key", pw);
  prep.onload = () => {
    if (prep.status !== 200) return fail(prep);
    const j = JSON.parse(prep.responseText);
    fname.textContent = fileObj.name;
    const href = location.origin + "/f/" + j.ok;
    url.value = href;
    show(done, true);
    popToast("Link ready");
    uploadBody("/upload/" + j.ok, fileObj, pw);
  };
  prep.onerror = () => fail(prep);
  prep.send();
}

function fail(req) {
  let msg = "error " + req.status;
  try {
    msg = JSON.parse(req.responseText).error || msg;
  } catch (_) {}
  banner.textContent = msg;
  show(banner, true);
  show(bar, false);
  show(pct, false);
  show(cancel, false);
  checkKey();
}

function uploadBody(path, fileObj, pw) {
  const xhr = new XMLHttpRequest();
  current = xhr;
  xhr.open("POST", path);
  xhr.setRequestHeader("X-Upload-Key", pw);
  let last = 0;
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const p = Math.round((e.loaded / e.total) * 100);
    const now = Date.now();
    const secs = (now - last) / 1000 || 0;
    last = now;
    const speed = secs > 0 ? e.loaded / secs : 0;
    const remain = e.total > e.loaded ? (e.total - e.loaded) / Math.max(speed, 1) : 0;
    fill.style.width = p + "%";
    pct.textContent = p + "% · " + fmtBytes(e.loaded) + " · " + fmtBytes(speed) + "/s · " + fmtTime(remain) + " left";
  };
  xhr.onload = () => {
    if (xhr.status === 200) {
      loadStatus();
      popToast("Upload complete");
    } else {
      fail(xhr);
    }
    show(bar, false);
    show(pct, false);
    show(cancel, false);
    checkKey();
  };
  xhr.onerror = () => {
    banner.textContent = "upload failed";
    show(banner, true);
    show(bar, false);
    show(pct, false);
    show(cancel, false);
    checkKey();
  };
  xhr.send(fileObj);
}

cancel.addEventListener("click", () => {
  if (current) current.abort();
  const token = url.value.split("/").pop();
  if (token) {
    fetch("/upload/" + encodeURIComponent(token), {
      method: "DELETE",
      headers: { "X-Upload-Key": key.value.trim() },
    }).catch(() => {});
  }
  current = null;
  show(bar, false);
  show(pct, false);
  show(cancel, false);
  show(done, false);
  banner.textContent = "Upload cancelled.";
  show(banner, true);
  checkKey();
});

pick.addEventListener("click", () => file.click());
file.addEventListener("change", () => {
  if (file.files[0]) start(file.files[0]);
});

drop.addEventListener("dragover", (e) => {
  e.preventDefault();
  drop.classList.add("over");
});
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  if (e.dataTransfer.files[0]) start(e.dataTransfer.files[0]);
});
drop.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    if (!drop.classList.contains("disabled")) file.click();
  }
});

function markCopied() {
  copy.textContent = "Copied!";
  popToast("Link copied!");
  setTimeout(() => (copy.textContent = "COPY"), 1500);
}

copy.addEventListener("click", () => {
  const ok = () => markCopied();
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(url.value).then(ok, () => {
      url.select();
      document.execCommand("copy");
      ok();
    });
  } else {
    url.select();
    document.execCommand("copy");
    ok();
  }
});