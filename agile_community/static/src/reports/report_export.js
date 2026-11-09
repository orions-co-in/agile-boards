// Files a report gives away (U-1162): a CSV from the numbers on screen, a PNG of the chart on screen.
import { Component, useProps, t } from "@odoo/owl";
import { downloadBlob, downloadText, fileSlug } from "../dashboard/dashboard_export";

const STYLE_PROPS = [
    "fill", "fill-opacity", "stroke", "stroke-width", "stroke-dasharray", "stroke-opacity", "opacity",
    "font-family", "font-size", "font-weight", "text-anchor",
];

/** One CSV cell: quoted when needed, and a leading = + - @ gets a quote so a spreadsheet never runs it. */
export function csvCell(value) {
    let text = value === null || value === undefined || value === false ? "" : String(value);
    if (/^[=+\-@\t\r]/.test(text) && !/^-?\d+(\.\d+)?$/.test(text)) {
        text = `'${text}`;
    }
    return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function csvText(columns, rows) {
    return [columns, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
}

/** "sprint-1-burnup-2026-11-02.csv" */
export function reportFileName(title, extension, today = new Date()) {
    return `${fileSlug(title)}-${today.toISOString().slice(0, 10)}.${extension}`;
}

/** A copy of the chart whose colours and fonts are written into it, so it looks the same away from the page. */
function inlineStyles(source, copy) {
    const style = getComputedStyle(source);
    for (const prop of STYLE_PROPS) {
        copy.style.setProperty(prop, style.getPropertyValue(prop));
    }
    [...source.children].forEach((child, index) => inlineStyles(child, copy.children[index]));
}

/** Draw the chart's SVG under a title line on a white canvas, twice the size for sharpness. */
export async function svgPngBlob(svg, title, subtitle = "") {
    const box = svg.viewBox.baseVal;
    const width = box.width || svg.clientWidth;
    const height = box.height || svg.clientHeight;
    const copy = svg.cloneNode(true);
    inlineStyles(svg, copy);
    copy.querySelectorAll(".o_ag_cfd_cursor").forEach((node) => node.remove());
    copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    copy.setAttribute("width", width);
    copy.setAttribute("height", height);
    const markup = new XMLSerializer().serializeToString(copy);
    const image = new Image();
    await new Promise((resolve, reject) => {
        image.onload = resolve;
        image.onerror = reject;
        image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`;
    });
    const head = 64;
    const scale = 2;
    const canvas = document.createElement("canvas");
    canvas.width = width * scale;
    canvas.height = (height + head) * scale;
    const ctx = canvas.getContext("2d");
    ctx.scale(scale, scale);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height + head);
    ctx.fillStyle = "#1d2733";
    ctx.font = "bold 20px sans-serif";
    ctx.fillText(title, 16, 30);
    ctx.fillStyle = "#5d6975";
    ctx.font = "13px sans-serif";
    ctx.fillText(subtitle, 16, 52);
    ctx.drawImage(image, 0, head, width, height);
    return new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
}

/** A plain picture of the sprint report: its question, planned and delivered bars and the four counts. */
export function sprintPngBlob(title, subtitle, bars, counts) {
    const width = 720;
    const height = 120 + bars.length * 34 + counts.length * 26 + 30;
    const canvas = document.createElement("canvas");
    canvas.width = width * 2;
    canvas.height = height * 2;
    const ctx = canvas.getContext("2d");
    ctx.scale(2, 2);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = "#1d2733";
    ctx.font = "bold 20px sans-serif";
    ctx.fillText(title, 16, 30);
    ctx.fillStyle = "#5d6975";
    ctx.font = "13px sans-serif";
    ctx.fillText(subtitle, 16, 52);
    let y = 84;
    bars.forEach((bar, index) => {
        ctx.fillStyle = "#1d2733";
        ctx.fillText(bar.label, 16, y + 14);
        ctx.fillStyle = index ? "#017e84" : "#b7c0c9";
        ctx.fillRect(110, y, Math.max(2, (bar.percent / 100) * 480), 20);
        ctx.fillStyle = "#1d2733";
        ctx.fillText(bar.text, 118 + (bar.percent / 100) * 480, y + 14);
        y += 34;
    });
    y += 16;
    for (const count of counts) {
        ctx.fillStyle = "#1d2733";
        ctx.font = "bold 14px sans-serif";
        ctx.fillText(String(count.count), 16, y);
        ctx.font = "13px sans-serif";
        ctx.fillText(`${count.label}: ${count.text}`, 56, y);
        y += 26;
    }
    return new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
}

/**
 * The two download buttons of a report. `table()` gives { columns, rows } of what is on screen;
 * `png()` gives the image blob (and is left out when a report has no picture).
 */
export class ReportExport extends Component {
    static template = "agile_community.ReportExport";
    props = useProps({ title: t.string(), table: t.function(), png: t.function().optional()});

    downloadCsv() {
        const { columns, rows } = this.props.table();
        downloadText(reportFileName(this.props.title, "csv"), csvText(columns, rows));
    }

    async downloadPng() {
        const blob = await this.props.png();
        if (blob) {
            downloadBlob(reportFileName(this.props.title, "png"), blob);
        }
    }
}
