export function fmtNum(n) {
  if (n == null) return "—";
  return Number(n).toLocaleString("ko-KR", { maximumFractionDigits: 2 });
}

export function fmtPct(n) {
  if (n == null) return "—";
  const v = Number(n);
  const sign = v >= 0 ? "▲" : "▼";
  return `${sign}${Math.abs(v).toFixed(2)}%`;
}

export function pctClass(n) {
  return Number(n) >= 0 ? "up-text" : "down-text";
}

export function badgeClass(n) {
  const v = Number(n);
  if (v > 0) return "badge up";
  if (v < 0) return "badge down";
  return "badge flat";
}

export function showError(el, msg) {
  el.innerHTML = `<div class="error">${msg}</div>`;
}
