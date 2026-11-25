"use strict";

const blue = "#6199ff";
const teal = "#53d8ca";
const grid = "#26354b";
const textColor = "#b8c8df";

function chart(id, type, data, options = {}) {
    const element = document.getElementById(id);
    if (!element || !window.Chart) return null;
    return new Chart(element, { type, data, options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { display: false } },
        ...options
    }});
}

function dataset(label, data, color = blue) {
    return { label, data, borderColor: color, backgroundColor: color, borderWidth: 2,
        pointRadius: 1, tension: .22 };
}

function scales(x = {}, y = {}) {
    return {
        x: { grid: { color: grid }, ticks: { color: textColor, maxTicksLimit: 8 }, ...x },
        y: { grid: { color: grid }, ticks: { color: textColor }, ...y }
    };
}

const distribution = document.getElementById("distribution");
if (distribution) {
    chart("distribution", "doughnut", { labels: ["Normal", "Failure"], datasets: [{
        data: [Number(distribution.dataset.normal), Number(distribution.dataset.failed)],
        backgroundColor: [blue, teal], borderWidth: 0, spacing: 2
    }] }, { cutout: "78%" });
}

const comparison = document.getElementById("cv-table");
if (comparison) {
    const rows = [...comparison.tBodies[0].rows];
    chart("comparison", "bar", { labels: rows.map(row => row.cells[0].textContent),
        datasets: [{ data: rows.map(row => Number(row.cells[1].textContent.replace(",", "."))),
            backgroundColor: rows.map((row, index) => index === 0 ? teal : blue), borderRadius: 4 }] },
        { indexAxis: "y", scales: scales({min: 0, max: 1}) });
}

const loss = document.getElementById("loss");
if (loss) {
    const epochs = JSON.parse(loss.dataset.loss);
    chart("loss", "line", { labels: epochs.map(row => row.Epoch),
        datasets: [dataset("Weighted BCE", epochs.map(row => row.Loss))] }, { scales: scales() });
}

const feedElement = document.getElementById("sensor-feed");
if (feedElement) {
    const status = document.getElementById("feed-status");
    const tableBody = document.getElementById("sensor-rows");
    const series = [
        ["temp", ["air_temperature", "process_temperature"], ["Air", "Process"]],
        ["torque", ["torque"], ["Torque"]],
        ["speed", ["rotational_speed"], ["Speed"]],
        ["wear", ["tool_wear"], ["Wear"]]
    ];
    const charts = series.map(([id, keys, labels]) => chart(id, "line", {
        labels: [], datasets: keys.map((key, index) => dataset(labels[index], [], index === 0 ? blue : teal))
    }, { scales: scales(), plugins: { legend: { display: keys.length > 1, labels: { color: textColor } } } }));
    let previous = null;

    function render(feed, initial = false) {
        if (!feed) return;
        const entries = feed.readings;
        const ids = entries.map(entry => entry.event_id).join(",");
        if (ids !== previous) {
            const ordered = [...entries].reverse();
            const labels = ordered.map(entry => new Date(entry.event_time).toISOString().slice(11, 23));
            tableBody.replaceChildren(...entries.map(entry => {
                const row = document.createElement("tr");
                const timestamp = new Date(entry.event_time).toISOString().slice(0, 23).replace("T", " ");
                for (const value of [timestamp, entry.product_type, entry.air_temperature,
                    entry.process_temperature, entry.rotational_speed, entry.torque, entry.tool_wear]) {
                    row.insertCell().textContent = String(value);
                }
                return row;
            }));
            charts.forEach((item, i) => {
                if (!item) return;
                item.data.labels = labels;
                item.data.datasets.forEach((line, index) => {
                    line.data = ordered.map(entry => entry[series[i][1][index]]);
                });
                item.update("none");
            });
        }
        status.textContent = !feed.table_available ? "The streaming table is unavailable."
            : entries.length === 0 ? "No events have been stored yet."
            : initial ? "Showing the latest stored events."
            : ids === previous ? "No new stored events since the last check."
            : "The latest stored events have changed.";
        previous = ids;
    }

    render(JSON.parse(feedElement.dataset.initial), true);
    async function refresh() {
        try {
            const response = await fetch("/sensor-monitor/feed", { cache: "no-store" });
            if (!response.ok) throw new Error("Feed unavailable");
            render(await response.json());
        } catch {
            status.textContent = "The sensor feed is unavailable. Any readings shown are from the last successful check.";
        } finally {
            window.setTimeout(refresh, 15000);
        }
    }
    window.setTimeout(refresh, 15000);
}
