import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { formatFloat } from "@web/views/fields/formatters";
import { graphView } from "@web/views/graph/graph_view";
import { GraphRenderer } from "@web/views/graph/graph_renderer";

/** The backlog graph plus "Show the numbers": the same figures as a table, for screen readers and keyboards. */
export class AgileBacklogGraphRenderer extends GraphRenderer {
    static template = "agile_community.BacklogGraphRenderer";

    get measureLabel() {
        const { measure, measures } = this.model.metaData;
        return measures[measure]?.string || _t("Value");
    }

    get numberRows() {
        return (this.model.dataPoints || []).map((point) => ({
            label: point.labels.filter(Boolean).join(" · ") || _t("None"),
            value: formatFloat(point.value),
            count: point.count,
        }));
    }
}

export const agileBacklogGraphView = { ...graphView, Renderer: AgileBacklogGraphRenderer };

registry.category("views").add("agile_backlog_graph", agileBacklogGraphView);
