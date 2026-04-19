export function renderCandlestick(canvasId, data) {
  const ctx = document.getElementById(canvasId)?.getContext("2d");
  if (!ctx || !data?.length) return;

  const labels = data.map(d => d.date);
  const closes = data.map(d => d.close);

  new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "종가",
        data: closes,
        borderColor: "#2481cc",
        backgroundColor: "rgba(36,129,204,0.08)",
        fill: true,
        tension: 0.2,
        pointRadius: 0,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { maxTicksLimit: 6 } },
        y: { position: "right" },
      },
    },
  });
}
