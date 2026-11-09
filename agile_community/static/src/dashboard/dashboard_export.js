// Files a tile gives away (L-1044): a CSV from the server, a PNG drawn here from the chart's numbers.
import { barPercent, lineSegments, seriesMax } from "./dashboard_helpers";

const PALETTE = ["#714b67", "#017e84"];

export function downloadBlob(filename, blob) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadText(filename, text, type = "text/csv;charset=utf-8") {
    // A byte-order mark lets spreadsheet apps read accented names correctly.
    downloadBlob(filename, new Blob(["﻿", text], { type }));
}

export function fileSlug(title) {
    return String(title).replace(/[^A-Za-z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase() || "tile";
}

/** Draw one chart tile (title, date, chart and numbers) on a white canvas and return it. */
export function drawChart(title, chart, dateText) {
    const width = 800;
    const rowHeight = 22;
    const bars = chart.type === "bars";
    const barRows = bars ? chart.labels.length * chart.series.length : 0;
    const chartHeight = bars ? barRows * rowHeight + 10 : 220;
    const tableRows = chart.table.rows.length + 1;
    const height = 90 + chartHeight + 30 + tableRows * rowHeight + 20;
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = "#1d2733";
    ctx.font = "bold 22px sans-serif";
    ctx.fillText(title, 24, 36);
    ctx.fillStyle = "#5d6975";
    ctx.font = "14px sans-serif";
    ctx.fillText(dateText, 24, 58);
    let legendX = 24;
    if (chart.series.length > 1) {
        chart.series.forEach((series, index) => {
            ctx.fillStyle = PALETTE[index % PALETTE.length];
            ctx.fillRect(legendX, 68, 12, 12);
            ctx.fillStyle = "#1d2733";
            ctx.fillText(series.name, legendX + 18, 79);
            legendX += 30 + ctx.measureText(series.name).width + 18;
        });
    }
    const top = 90;
    const max = seriesMax(chart.series);
    ctx.font = "13px sans-serif";
    if (bars) {
        let y = top;
        chart.labels.forEach((label, index) => {
            chart.series.forEach((series, serie) => {
                ctx.fillStyle = "#1d2733";
                ctx.fillText(serie === 0 ? String(label).slice(0, 22) : "", 24, y + 14);
                ctx.fillStyle = PALETTE[serie % PALETTE.length];
                const size = (barPercent(series.values[index], max) / 100) * 480;
                ctx.fillRect(200, y + 3, size, 14);
                ctx.fillStyle = "#1d2733";
                ctx.fillText(String(series.values[index]), 208 + size, y + 14);
                y += rowHeight;
            });
        });
    } else {
        ctx.strokeStyle = "#dde1e6";
        ctx.strokeRect(24, top, width - 48, 200);
        chart.series.forEach((series, index) => {
            ctx.strokeStyle = PALETTE[index % PALETTE.length];
            ctx.lineWidth = 2.5;
            ctx.setLineDash(index ? [6, 4] : []);
            for (const run of lineSegments(series.values, max, width - 48, 200)) {
                ctx.beginPath();
                run.split(" ").forEach((point, position) => {
                    const [x, y] = point.split(",").map(Number);
                    position ? ctx.lineTo(24 + x, top + y) : ctx.moveTo(24 + x, top + y);
                });
                ctx.stroke();
            }
        });
        ctx.setLineDash([]);
    }
    let y = top + chartHeight + 30;
    const columns = chart.table.columns.length;
    const cell = (text, column, bold) => {
        ctx.font = `${bold ? "bold " : ""}13px sans-serif`;
        ctx.fillStyle = bold ? "#5d6975" : "#1d2733";
        ctx.fillText(String(text), 24 + column * ((width - 48) / columns), y);
    };
    chart.table.columns.forEach((name, column) => cell(name, column, true));
    for (const row of chart.table.rows) {
        y += rowHeight;
        row.forEach((value, column) => cell(value, column, false));
    }
    return canvas;
}

export function chartPngBlob(title, chart, dateText) {
    const canvas = drawChart(title, chart, dateText);
    return new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
}
