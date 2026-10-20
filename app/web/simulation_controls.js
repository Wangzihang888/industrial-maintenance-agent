
/*
 * 工业设备持续模拟控制台
 *
 * 功能：
 * 1. 四台设备独立持续采样
 * 2. 启动、切换场景、Recovery、停止
 * 3. 一键重演故障
 * 4. 查看故障事件与 Agent Task
 */

(() => {
    "use strict";

    const API = "/api/simulations/live";
    const POLL_INTERVAL = 2500;

    // 最长等待 Recovery 120 秒
    const REPLAY_TIMEOUT = 120000;

    const ROBOT_SCENARIOS = [
        ["normal", "Normal 正常运行"],
        ["e101", "E-101 编码器通信异常"],
        ["e102", "E-102 伺服驱动异常"],
        ["e103", "E-103 电机过热"],
        ["recovery", "Recovery 故障恢复"],
    ];

    const RGV_SCENARIOS = [
        ["normal", "Normal 正常运行"],
        ["recovery", "Recovery 温度恢复"],
    ];

    const DEFAULT_SCENARIOS = {
        "RB-001": "e101",
        "RB-002": "e102",
        "RB-003": "e103",
        "RGV-001": "normal",
    };

    const INCIDENT_KEYS = {
        e101: "encoder:communication",
        e102: "servo:drive_fault",
        e103: "temperature:overheat",
    };

    let devices = [];
    let sessions = {};
    let agentResults = {};

    const selectedScenarios = {};
    const busyDevices = new Set();

    let panel;
    let cardsContainer;
    let statusElement;
    let lastDashboardRefresh = 0;


    // ========================================================
    // 1. HTTP 请求
    // ========================================================

    async function apiRequest(url, options = {}) {
        const response = await fetch(url, options);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                typeof data.detail === "string"
                    ? data.detail
                    : "HTTP " + response.status
            );
        }

        return data;
    }

    function post(url, body) {
        return apiRequest(url, {
            method: "POST",
            headers: body
                ? { "Content-Type": "application/json" }
                : {},
            body: body
                ? JSON.stringify(body)
                : undefined,
        });
    }

    function sleep(milliseconds) {
        return new Promise(resolve => {
            setTimeout(resolve, milliseconds);
        });
    }


    // ========================================================
    // 2. 页面容器
    // ========================================================

    function buildPanel() {
        const main = document.querySelector("main");

        if (!main) {
            return;
        }

        panel = document.createElement("section");
        panel.className = "panel";

        const title = document.createElement("h2");
        title.textContent = "设备持续模拟监控";

        const description = document.createElement("p");
        description.textContent =
            "各设备独立采样。可以启动故障、恢复，"
            + "也可以一键重演同一种故障。";

        statusElement = document.createElement("p");
        statusElement.textContent = "正在加载设备...";

        cardsContainer = document.createElement("div");

        cardsContainer.style.display = "grid";
        cardsContainer.style.gridTemplateColumns =
            "repeat(auto-fit, minmax(270px, 1fr))";
        cardsContainer.style.gap = "14px";

        panel.append(
            title,
            description,
            statusElement,
            cardsContainer,
        );

        main.insertBefore(
            panel,
            main.firstElementChild
                ? main.firstElementChild.nextElementSibling
                : null
        );

        cardsContainer.addEventListener(
            "click",
            handleButtonClick
        );

        cardsContainer.addEventListener(
            "change",
            handleScenarioChange
        );
    }


    // ========================================================
    // 3. 基础元素
    // ========================================================

    function makeText(tag, value) {
        const element = document.createElement(tag);
        element.textContent = value;
        return element;
    }

    function makeButton(text, action, deviceId, disabled) {
        const button = document.createElement("button");

        button.type = "button";
        button.textContent = text;
        button.dataset.action = action;
        button.dataset.deviceId = deviceId;
        button.disabled = disabled;

        return button;
    }

    function getScenarios(deviceId) {
        return deviceId.startsWith("RB-")
            ? ROBOT_SCENARIOS
            : RGV_SCENARIOS;
    }


    // ========================================================
    // 4. 渲染设备卡片
    // ========================================================

    function buildDeviceCard(device) {
        const deviceId = device.device_id;
        const session = sessions[deviceId];

        const status = session
            ? session.status
            : "not_started";

        const running = status === "running";
        const busy = busyDevices.has(deviceId);

        const currentScenario = session
            ? session.scenario
            : null;

        const card = document.createElement("div");

        card.style.border = "1px solid #cbd5e1";
        card.style.borderRadius = "10px";
        card.style.padding = "14px";
        card.style.display = "flex";
        card.style.flexDirection = "column";
        card.style.gap = "10px";

        card.appendChild(
            makeText(
                "h3",
                (device.device_name || deviceId)
                + " (" + deviceId + ")"
            )
        );

        const labels = {
            not_started: "未启动",
            running: "持续运行中",
            stopping: "正在停止",
            stopped: "已停止",
            failed: "运行失败",
        };

        card.appendChild(
            makeText(
                "p",
                "运行状态：" + (labels[status] || status)
            )
        );

        card.appendChild(
            makeText(
                "p",
                "当前模拟温度："
                + (
                    session
                        ? Number(session.temperature).toFixed(1) + "℃"
                        : "暂无"
                )
                + " | 采样次数："
                + (session ? session.sample_count : 0)
            )
        );

        if (session) {
            card.appendChild(
                makeText(
                    "p",
                    "当前场景：" + currentScenario
                )
            );
        }

        // 场景选择
        const select = document.createElement("select");

        select.dataset.deviceId = deviceId;
        select.style.padding = "9px";
        select.style.borderRadius = "7px";

        const selected = selectedScenarios[deviceId]
            || currentScenario
            || DEFAULT_SCENARIOS[deviceId]
            || "normal";

        for (const [value, label] of getScenarios(deviceId)) {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = label;
            select.appendChild(option);
        }

        select.value = selected;

        if (!select.value) {
            select.value = "normal";
        }

        select.disabled = busy;
        card.appendChild(select);

        // 操作按钮
        const buttons = document.createElement("div");

        buttons.style.display = "flex";
        buttons.style.flexWrap = "wrap";
        buttons.style.gap = "8px";

        buttons.append(
            makeButton(
                "启动",
                "start",
                deviceId,
                busy || running || status === "stopping"
            ),
            makeButton(
                "切换场景",
                "change",
                deviceId,
                busy || !running
            ),
            makeButton(
                "Recovery",
                "recovery",
                deviceId,
                busy || !running
            ),
            makeButton(
                "一键重演故障",
                "replay",
                deviceId,
                busy || !running
                    || !INCIDENT_KEYS[currentScenario]
            ),
            makeButton(
                "停止",
                "stop",
                deviceId,
                busy || !running
            )
        );

        card.appendChild(buttons);

        // 最近故障事件
        const events = session?.last_events || [];

        const eventText = events.length
            ? events.map(event => (
                (event.alarm_code || event.incident_key)
                + " / " + event.risk_level
                + " / " + event.incident_id
            )).join("\n")
            : "本次采样未检测到异常";

        card.appendChild(
            makeText("p", "最近故障事件：")
        );

        const eventDetail = makeText("pre", eventText);
        eventDetail.style.whiteSpace = "pre-wrap";
        eventDetail.style.overflowWrap = "anywhere";
        eventDetail.style.fontSize = "12px";
        card.appendChild(eventDetail);

        // 本次会话创建的 Task
        const taskIds = session?.created_task_ids || [];

        const taskText = taskIds.length
            ? taskIds.slice(-5).map(taskId => (
                taskId + " → "
                + (agentResults[taskId]?.status || "queued")
            )).join("\n")
            : "本次会话无新任务";

        card.appendChild(
            makeText("p", "Agent Task：")
        );

        const taskDetail = makeText("pre", taskText);
        taskDetail.style.whiteSpace = "pre-wrap";
        taskDetail.style.overflowWrap = "anywhere";
        taskDetail.style.fontSize = "12px";
        card.appendChild(taskDetail);

        if (session?.error) {
            card.appendChild(
                makeText("p", "错误：" + session.error)
            );
        }

        return card;
    }

    function renderDevices() {
        if (!cardsContainer) {
            return;
        }

        cardsContainer.replaceChildren(
            ...devices.map(buildDeviceCard)
        );
    }


    // ========================================================
    // 5. 加载设备与模拟状态
    // ========================================================

    async function loadDevices() {
        const result = await apiRequest("/api/devices");
        devices = result.devices || [];

        renderDevices();
    }

    async function fetchSessions() {
        const result = await apiRequest(
            API + "/devices"
        );

        sessions = Object.fromEntries(
            (result.devices || []).map(
                session => [
                    session.device_id,
                    session,
                ]
            )
        );

        agentResults = result.agent_results || {};
        renderDevices();
    }

    async function refreshLiveStatus() {
        try {
            await fetchSessions();

            const runningCount = Object.values(sessions)
                .filter(
                    session => session.status === "running"
                ).length;

            statusElement.textContent =
                "持续运行设备：" + runningCount
                + " / " + devices.length;

            // 原有设备、Incident、Task、审批列表
            // 每约 8 秒自动刷新一次。
            const now = Date.now();

            if (
                now - lastDashboardRefresh >= 8000
                && typeof window.refreshAll === "function"
            ) {
                lastDashboardRefresh = now;

                try {
                    await window.refreshAll();
                } catch (error) {
                    console.warn("工作台刷新失败：", error);
                }
            }

        } catch (error) {
            statusElement.textContent =
                "查询失败：" + error.message;
        }
    }


    // ========================================================
    // 6. 查询指定故障的活动 Incident
    // ========================================================

    async function getActiveIncident(deviceId, incidentKey) {
        const result = await apiRequest(
            "/api/incidents?limit=100"
        );

        return (result.incidents || []).find(
            item => (
                item.device_id === deviceId
                && item.incident_key === incidentKey
                && item.status === "open"
            )
        ) || null;
    }


    // ========================================================
    // 7. 等待旧 Incident 恢复关闭
    // ========================================================

    async function waitForRecovery(
        deviceId,
        incidentKey,
        oldIncidentId,
        startingCount
    ) {
        const deadline = Date.now() + REPLAY_TIMEOUT;

        while (Date.now() < deadline) {
            await sleep(POLL_INTERVAL);
            await fetchSessions();

            const session = sessions[deviceId];

            if (!session || session.status !== "running") {
                throw new Error(
                    "设备已停止，无法继续重演"
                );
            }

            // 确认至少发生过 3 次新采样，
            // 避免在无旧 Incident 时立即切回故障。
            if (
                session.sample_count - startingCount < 3
            ) {
                continue;
            }

            const active = await getActiveIncident(
                deviceId,
                incidentKey
            );

            if (!active) {
                return;
            }

            // 若有另一个活动 Incident，
            // 不能误认为原故障已经恢复完成。
            if (
                oldIncidentId
                && active.incident_id !== oldIncidentId
            ) {
                throw new Error(
                    "检测到新的活动 Incident，停止自动重演"
                );
            }
        }

        throw new Error(
            "Recovery 超时，旧 Incident 尚未关闭。"
            + "请检查设备状态后手动操作。"
        );
    }


    // ========================================================
    // 8. 一键重演故障
    // ========================================================

    async function replayFault(deviceId) {
        const session = sessions[deviceId];

        if (!session || session.status !== "running") {
            throw new Error("请先启动设备");
        }

        // 重演当前正在运行的故障，
        // 不使用下拉框中尚未生效的选择。
        const originalScenario = session.scenario;
        const incidentKey = INCIDENT_KEYS[originalScenario];

        if (!incidentKey) {
            throw new Error(
                "当前场景不是可重演的故障场景"
            );
        }

        const oldIncident = await getActiveIncident(
            deviceId,
            incidentKey
        );

        const oldIncidentId = oldIncident?.incident_id || null;

        const startingCount = session.sample_count;

        statusElement.textContent =
            deviceId + "：正在恢复旧故障...";

        // 第一步：切换 Recovery
        await post(
            API + "/" + encodeURIComponent(deviceId)
            + "/scenario",
            { scenario: "recovery" }
        );

        selectedScenarios[deviceId] = "recovery";

        // 第二步：等待旧 Incident 消失
        await waitForRecovery(
            deviceId,
            incidentKey,
            oldIncidentId,
            startingCount
        );

        statusElement.textContent =
            deviceId + "：旧故障已恢复，正在重新触发...";

        // 第三步：重新切回故障场景
        await post(
            API + "/" + encodeURIComponent(deviceId)
            + "/scenario",
            { scenario: originalScenario }
        );

        selectedScenarios[deviceId] = originalScenario;

        await fetchSessions();

        statusElement.textContent =
            deviceId + "：已重新触发 "
            + originalScenario
            + "，等待监控系统生成新 Incident 和 Task。";
    }


    // ========================================================
    // 9. 下拉框事件
    // ========================================================

    function handleScenarioChange(event) {
        const select = event.target.closest("select");

        if (!select) {
            return;
        }

        selectedScenarios[select.dataset.deviceId] =
            select.value;
    }


    // ========================================================
    // 10. 按钮事件
    // ========================================================

    async function handleButtonClick(event) {
        const button = event.target.closest(
            "button[data-action]"
        );

        if (!button) {
            return;
        }

        const deviceId = button.dataset.deviceId;
        const action = button.dataset.action;

        if (busyDevices.has(deviceId)) {
            return;
        }

        busyDevices.add(deviceId);
        renderDevices();

        try {
            const base = API + "/"
                + encodeURIComponent(deviceId);

            const scenario = selectedScenarios[deviceId]
                || sessions[deviceId]?.scenario
                || DEFAULT_SCENARIOS[deviceId]
                || "normal";

            if (action === "start") {
                await post(base + "/start", {
                    scenario,
                    interval: 2,
                });

            } else if (action === "change") {
                await post(base + "/scenario", {
                    scenario,
                });

            } else if (action === "recovery") {
                await post(base + "/scenario", {
                    scenario: "recovery",
                });

                selectedScenarios[deviceId] = "recovery";

            } else if (action === "stop") {
                await post(base + "/stop");

            } else if (action === "replay") {
                await replayFault(deviceId);

            } else {
                return;
            }

            await refreshLiveStatus();

        } catch (error) {
            statusElement.textContent =
                deviceId + " 操作失败："
                + error.message;

        } finally {
            busyDevices.delete(deviceId);
            renderDevices();
        }
    }


    // ========================================================
    // 11. 初始化
    // ========================================================

    async function initialize() {
        buildPanel();

        if (!panel) {
            return;
        }

        try {
            await loadDevices();
            await refreshLiveStatus();

            window.setInterval(
                refreshLiveStatus,
                POLL_INTERVAL
            );

        } catch (error) {
            statusElement.textContent =
                "初始化失败：" + error.message;
        }
    }

    initialize();

})();
