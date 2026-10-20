
/*
 * AI 人工运维助手
 *
 * 功能：
 * 1. 向 /api/chat 发送自然语言问题
 * 2. 显示用户与 Agent 的对话
 * 3. 保存并复用 thread_id，实现多轮对话
 * 4. 新建独立会话
 * 5. 展示当前设备上下文
 *
 * 不负责：
 * - 自动检测设备故障
 * - 直接创建维修工单
 * - 修改 Incident 或审批状态
 */

(() => {
    "use strict";

    const CHAT_API = "/api/chat";

    // 当前网页会话的 LangGraph Thread ID
    let threadId = null;

    // 是否正在等待 Agent 回复
    let sending = false;

    let panel;
    let messagesBox;
    let input;
    let sendButton;
    let newChatButton;
    let statusText;
    let contextText;


    // ========================================================
    // 1. 创建基础元素
    // ========================================================

    function makeElement(tag, text = "") {
        const element = document.createElement(tag);

        if (text) {
            element.textContent = text;
        }

        return element;
    }


    // ========================================================
    // 2. 添加聊天消息
    // ========================================================

    function appendMessage(role, content) {
        const wrapper = document.createElement("div");

        wrapper.style.display = "flex";
        wrapper.style.justifyContent = (
            role === "user"
                ? "flex-end"
                : "flex-start"
        );

        const bubble = document.createElement("div");

        bubble.style.maxWidth = "88%";
        bubble.style.padding = "12px 15px";
        bubble.style.borderRadius = "12px";
        bubble.style.whiteSpace = "pre-wrap";
        bubble.style.overflowWrap = "anywhere";
        bubble.style.lineHeight = "1.8";
        bubble.style.fontSize = "14px";

        if (role === "user") {
            bubble.style.background = "#dbeafe";
            bubble.style.color = "#1e3a8a";
        } else {
            bubble.style.background = "#f1f5f9";
            bubble.style.color = "#202b3c";
        }

        // 使用 textContent，避免模型回答被当成 HTML 执行
        bubble.textContent = content;

        wrapper.appendChild(bubble);
        messagesBox.appendChild(wrapper);

        messagesBox.scrollTop = messagesBox.scrollHeight;

        return bubble;
    }


    // ========================================================
    // 3. 更新会话状态
    // ========================================================

    function setStatus(message) {
        statusText.textContent = message;
    }

    function setSending(value) {
        sending = value;

        sendButton.disabled = value;
        newChatButton.disabled = value;
        input.disabled = value;

        sendButton.textContent = value
            ? "正在思考..."
            : "发送";
    }


    // ========================================================
    // 4. 构建聊天面板
    // ========================================================

    function buildPanel() {
        const main = document.querySelector("main");

        if (!main) {
            return;
        }

        panel = makeElement("section");
        panel.className = "panel";
        panel.id = "ai-chat-panel";

        const title = makeElement(
            "h2",
            "AI 运维助手"
        );

        const description = makeElement(
            "p",
            "支持设备状态查询、E-101 / E-102 / E-103 "
            + "维修知识问答和多轮故障分析。"
            + "回答应以设备数据和知识库证据为依据。"
        );

        description.style.color = "#64748b";
        description.style.fontSize = "14px";

        // 当前会话信息
        const topBar = makeElement("div");

        topBar.style.display = "flex";
        topBar.style.alignItems = "center";
        topBar.style.justifyContent = "space-between";
        topBar.style.flexWrap = "wrap";
        topBar.style.gap = "10px";
        topBar.style.marginBottom = "12px";

        contextText = makeElement(
            "span",
            "当前设备：未指定"
        );

        contextText.style.fontSize = "13px";
        contextText.style.color = "#475569";

        newChatButton = makeElement(
            "button",
            "新建对话"
        );

        newChatButton.type = "button";
        newChatButton.className = "secondary";

        topBar.append(
            contextText,
            newChatButton
        );

        // 消息显示区域
        messagesBox = makeElement("div");

        messagesBox.id = "ai-chat-messages";
        messagesBox.setAttribute(
            "role",
            "log"
        );
        messagesBox.setAttribute(
            "aria-label",
            "AI 运维助手对话记录"
        );

        messagesBox.style.height = "370px";
        messagesBox.style.overflowY = "auto";
        messagesBox.style.padding = "16px";
        messagesBox.style.border = "1px solid #e2e8f0";
        messagesBox.style.borderRadius = "10px";
        messagesBox.style.display = "flex";
        messagesBox.style.flexDirection = "column";
        messagesBox.style.gap = "12px";
        messagesBox.style.background = "#ffffff";

        // 快捷问题
        const examples = makeElement("div");

        examples.style.display = "flex";
        examples.style.flexWrap = "wrap";
        examples.style.gap = "8px";
        examples.style.marginTop = "12px";

        const exampleQuestions = [
            [
                "E-101 排查",
                "RB-001 出现 E-101 编码器通信异常，"
                + "根据维修手册应该怎样排查？"
            ],
            [
                "E-102 排查",
                "RB-002 出现 E-102 伺服驱动异常，"
                + "应该优先检查什么？"
            ],
            [
                "E-103 排查",
                "RB-003 出现 E-103 电机过热，"
                + "有哪些可能原因和安全注意事项？"
            ],
            [
                "对比 E-101 / E-102",
                "请对比 E-101 和 E-102 的故障原因、"
                + "排查顺序和安全注意事项，"
                + "严格依据维修知识库回答。"
            ],
        ];

        for (const [label, question] of exampleQuestions) {
            const button = makeElement(
                "button",
                label
            );

            button.type = "button";
            button.className = "secondary";
            button.style.fontSize = "12px";

            button.addEventListener(
                "click",
                () => {
                    if (sending) {
                        return;
                    }

                    input.value = question;
                    input.focus();
                }
            );

            examples.appendChild(button);
        }

        // 输入区域
        const inputArea = makeElement("div");

        inputArea.style.display = "flex";
        inputArea.style.gap = "10px";
        inputArea.style.marginTop = "12px";
        inputArea.style.alignItems = "flex-end";

        input = makeElement("textarea");

        input.id = "ai-chat-input";
        input.rows = 3;
        input.maxLength = 2000;

        input.placeholder = (
            "请输入运维问题，例如："
            + "E-101 编码器通信异常应该如何排查？"
        );

        input.style.flex = "1";
        input.style.minWidth = "0";
        input.style.padding = "12px";
        input.style.resize = "vertical";
        input.style.border = "1px solid #cbd5e1";
        input.style.borderRadius = "8px";
        input.style.fontFamily = "inherit";
        input.style.fontSize = "14px";

        sendButton = makeElement(
            "button",
            "发送"
        );

        sendButton.type = "button";

        inputArea.append(
            input,
            sendButton
        );

        statusText = makeElement(
            "p",
            "准备就绪"
        );

        statusText.style.fontSize = "13px";
        statusText.style.color = "#64748b";
        statusText.setAttribute("role", "status");

        panel.append(
            title,
            description,
            topBar,
            messagesBox,
            examples,
            inputArea,
            statusText
        );

        main.appendChild(panel);

        // 绑定交互事件
        sendButton.addEventListener(
            "click",
            sendMessage
        );

        newChatButton.addEventListener(
            "click",
            resetConversation
        );

        // Enter 发送；Shift + Enter 换行
        input.addEventListener(
            "keydown",
            event => {
                if (
                    event.key === "Enter"
                    && !event.shiftKey
                    && !event.isComposing
                ) {
                    event.preventDefault();

                    sendMessage();
                }
            }
        );

        showWelcomeMessage();
    }


    // ========================================================
    // 5. 欢迎消息
    // ========================================================

    function showWelcomeMessage() {
        appendMessage(
            "assistant",
            "你好，我是 AI 运维助手。\n\n"
            + "你可以向我咨询工业机器人故障原因、"
            + "维修手册排查步骤，也可以让我查询"
            + "设备的当前状态和历史记录。\n\n"
            + "例如：RB-001 出现 E-101，"
            + "应该按照什么顺序排查？"
        );
    }


    // ========================================================
    // 6. 发送消息并调用真实 Agent
    // ========================================================

    async function sendMessage() {
        if (sending) {
            return;
        }

        const message = input.value.trim();

        if (!message) {
            setStatus("请输入问题后再发送");
            return;
        }

        if (message.length > 2000) {
            setStatus("问题不能超过 2000 个字符");
            return;
        }

        appendMessage("user", message);

        input.value = "";
        setSending(true);
        setStatus("Agent 正在查询工具和知识库...");

        // 用于出现错误时允许重新编辑原问题
        const pendingBubble = appendMessage(
            "assistant",
            "正在分析，请稍候..."
        );

        try {
            const response = await fetch(
                CHAT_API,
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        message: message,
                        thread_id: threadId,
                    }),
                }
            );

            const result = await response.json();

            if (!response.ok) {
                throw new Error(
                    typeof result.detail === "string"
                        ? result.detail
                        : "HTTP " + response.status
                );
            }

            if (
                result.success !== true
                || typeof result.answer !== "string"
                || !result.thread_id
            ) {
                throw new Error(
                    "聊天接口返回的数据格式不完整"
                );
            }

            // 第一次调用保存后端生成的 Thread ID。
            // 后续对话继续传回这个 ID。
            threadId = result.thread_id;

            pendingBubble.textContent = (
                result.answer.trim()
                || "Agent 没有返回可显示的文字回答。"
            );

            const device = (
                result.current_device_id
                || "未指定"
            );

            const incident = result.current_incident_id;

            contextText.textContent = (
                "当前设备：" + device
                + (
                    incident
                        ? " | Incident：" + incident
                        : ""
                )
            );

            setStatus("回答完成，可以继续追问");

        } catch (error) {
            pendingBubble.textContent = (
                "请求失败：" + error.message
            );

            // 还原问题，方便重新尝试
            input.value = message;

            setStatus(
                "请求失败，请检查 FastAPI 日志。"
                + "如果服务器已执行但响应中断，"
                + "再次发送可能导致问题重复处理。"
            );

        } finally {
            setSending(false);
            input.focus();
        }
    }


    // ========================================================
    // 7. 新建独立会话
    // ========================================================

    function resetConversation() {
        if (sending) {
            return;
        }

        // 不传旧 Thread ID，下一次请求生成新会话
        threadId = null;

        messagesBox.replaceChildren();

        contextText.textContent = (
            "当前设备：未指定"
        );

        input.value = "";

        showWelcomeMessage();

        setStatus("已新建对话");
        input.focus();
    }


    // ========================================================
    // 8. 初始化
    // ========================================================

    buildPanel();

})();
