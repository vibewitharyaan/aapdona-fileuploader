const token = location.pathname.split("/").pop();
const dl = document.getElementById("dl");
dl.href = "/f/" + encodeURIComponent(token) + "?dl=1";

fetch("/f/" + encodeURIComponent(token) + "?info=1")
  .then((r) => r.json())
  .then((j) => {
    document.getElementById("name").textContent = j.name;
    document.getElementById("size").textContent = fmtBytes(j.size);
    document.getElementById("eta").textContent =
      "~" + fmtBytes(j.bandwidth) + "/s · about " + fmtTime(j.eta) + " left";
    if (j.once) {
      document.getElementById("expiry").textContent = "Deletes after this download.";
    } else if (j.expires_at) {
      const h = (j.expires_at - Date.now() / 1000) / 3600;
      document.getElementById("expiry").textContent =
        "Available for " + (h >= 24 ? (h / 24).toFixed(1) + " days" : Math.round(h) + " hours");
    }
  })
  .catch(() => {
    document.getElementById("name").textContent = "file gone";
    dl.removeAttribute("href");
  });

function fmtBytes(n) {
  if (n >= 1024 ** 3) return (n / 1024 ** 3).toFixed(2) + " GB";
  if (n >= 1024 ** 2) return (n / 1024 ** 2).toFixed(1) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(0) + " KB";
  return n + " B";
}

function fmtTime(s) {
  if (s < 60) return Math.round(s) + "s";
  if (s < 3600) return Math.floor(s / 60) + "m " + Math.round(s % 60) + "s";
  return Math.floor(s / 3600) + "h " + Math.round((s % 3600) / 60) + "m";
}