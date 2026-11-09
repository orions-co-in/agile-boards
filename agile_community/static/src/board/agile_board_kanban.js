import { onWillStart, proxy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { projectTaskKanbanView } from "@project/views/project_task_kanban/project_task_kanban_view";
import { ProjectTaskKanbanController } from "@project/views/project_task_kanban/project_task_kanban_controller";
import { AgileBoardBar } from "./agile_board_bar";
import { AgileBulkBar } from "@agile_community/bulk/agile_bulk_bar";
import { AgileCardDrawer } from "./agile_card_drawer";
import { AgileBoardKanbanRenderer } from "./agile_board_renderer";
import { useLayoutEffect, useSubEnv } from "@web/owl2/utils";

export class AgileBoardKanbanController extends ProjectTaskKanbanController {
    static template = "agile_community.BoardKanbanView";
    static components = { ...ProjectTaskKanbanController.components, AgileBoardBar, AgileCardDrawer, AgileBulkBar };

    setup() {
        super.setup();
        this.board = proxy({ swimlane: this.props.context.agile_swimlane || "none" });
        this.drawer = proxy({ resId: null });
        // Select mode (S-931): a click on a card picks it for the bulk bar instead of opening the drawer.
        this.select = proxy({ on: false, ids: [] });
        useSubEnv({ agileSelect: this.select });
        this.drawerLeave = null;
        // Stage counts for the WIP badges, shared with the column headers.
        this.boardData = proxy({ wip: {}, columns: [], columnGroups: [] });
        useSubEnv({ agileBoard: this.boardData });
        this.orm = useService("orm");
        onWillStart(() => this.loadWip());
        useLayoutEffect(
            () => {
                this.loadWip();
            },
            () => [this.headerRefreshKey]
        );
    }

    async loadWip() {
        const projectId = this.boardProjectId;
        if (!projectId) {
            return;
        }
        try {
            const data = await this.orm.call("project.project", "agile_board_wip", [[projectId]]);
            this.boardData.wip = Object.fromEntries(data.stages.map((stage) => [stage.stage_id, stage]));
        } catch {
            // Without the counts the columns simply show no badge.
            this.boardData.wip = {};
        }
    }

    get drawerViewId() {
        return this.props.context.agile_drawer_view_id;
    }

    /** A click on a card opens the drawer (full screen on a phone); new-window clicks and other boards use the form page. */
    async openRecord(record, options = {}) {
        if (this.select?.on) {
            return this.toggleSelected(record.resId);
        }
        if (options.newWindow || !this.drawerViewId) {
            return super.openRecord(record, options);
        }
        if (this.drawer.resId === record.resId) {
            return;
        }
        if (this.drawerLeave) {
            if (!(await this.drawerLeave())) {
                return;
            }
            // What was edited for the previous issue shows on the board right away.
            await this.model.load();
        }
        this.drawerOpenerKey = record.data.issue_key;
        this.drawer.resId = record.resId;
    }

    toggleSelected(resId) {
        const at = this.select.ids.indexOf(resId);
        if (at >= 0) {
            this.select.ids.splice(at, 1);
        } else {
            this.select.ids.push(resId);
        }
    }

    toggleSelectMode() {
        this.select.on = !this.select.on;
        this.select.ids = [];
    }

    clearSelected() {
        this.select.ids = [];
    }

    async onBulkDone({ refused }) {
        await this.model.load();
        this.select.ids = refused;
    }

    registerDrawerLeave(leave) {
        this.drawerLeave = leave;
    }

    async closeDrawer() {
        this.drawer.resId = null;
        this.drawerLeave = null;
        await this.model.load();
        this.focusOpener();
    }

    /** Give focus back to the card that opened the drawer. */
    focusOpener() {
        const key = this.drawerOpenerKey;
        setTimeout(() => {
            const card = [...document.querySelectorAll(".o_kanban_record")].find((el) =>
                key && el.innerText.includes(key)
            );
            card?.focus();
        }, 0);
    }

    expandDrawer(resId) {
        const activeIds = this.model.root.records.map((record) => record.resId);
        this.drawer.resId = null;
        this.drawerLeave = null;
        return this.props.selectRecord(resId, { activeIds });
    }

    get boardProjectId() {
        return this.props.context.default_project_id;
    }

    /** Changes whenever cards move between columns, so the header numbers follow. */
    get headerRefreshKey() {
        const groups = this.model.root.groups || [];
        return groups.map((group) => `${group.value}:${group.list.records.length}`).join(",");
    }

    /** Changes whenever a quick filter is switched, so the bar redraws and saves it. */
    get barFilterKey() {
        const items = this.env.searchModel.getSearchItems(
            (item) => item.type === "filter" && (item.agileBoardKey || item.agileBoardQuery || ["agile_quick_my_issues", "agile_blocked"].includes(item.name))
        );
        return items.map((item) => `${item.id}:${item.isActive ? 1 : 0}`).join(",");
    }

    /** The stages the current board shows; empty means every column. */
    setColumns(ids, groups = []) {
        this.boardData.columns = ids;
        this.boardData.columnGroups = groups;
    }

    setSwimlane(value) {
        this.board.swimlane = value;
    }

    reloadBoard() {
        return this.model.load();
    }
}

export const agileBoardKanbanView = {
    ...projectTaskKanbanView,
    Controller: AgileBoardKanbanController,
    Renderer: AgileBoardKanbanRenderer,
};

registry.category("views").add("agile_board_kanban", agileBoardKanbanView);
