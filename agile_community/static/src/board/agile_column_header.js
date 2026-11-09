import { ProjectTaskKanbanHeader } from "@project/views/project_task_kanban/project_task_kanban_header";
import { columnFacts } from "./board_helpers";

/** The core column header plus the blocked count and the WIP badge. */
export class AgileColumnHeader extends ProjectTaskKanbanHeader {
    static template = "agile_community.ColumnHeader";

    get facts() {
        return columnFacts(this.props.group, this.env.agileBoard?.wip);
    }
}
