"""
Crew Demo - 周报聚合场景
最小可演示版本 v0.2

新增：visibility 字段（public | private_to_sender | private_to_target | private_to_group）

run: python src/app.py
"""
from flask import Flask, jsonify, request
from datetime import datetime
import uuid

app = Flask(__name__)

# ============ 数据模型 ============

class Pheromone:
    def __init__(self, id=None, type=None, sender=None, targets=None, content=None,
                 parent_pheromone_id=None, judgment_status="pending", metadata=None,
                 visibility="public", visible_to=None):
        self.id = id or str(uuid.uuid4())[:8]
        self.type = type
        self.sender = sender
        self.targets = targets or []
        self.content = content
        self.parent_pheromone_id = parent_pheromone_id
        self.judgment_status = judgment_status
        self.metadata = metadata or {}
        self.visibility = visibility  # public | private_to_sender | private_to_target | private_to_group
        self.visible_to = visible_to or []  # 私有可见对象列表 ["EP001", "EP002"]
        self.timestamp = datetime.utcnow().isoformat() + "Z"

    def to_dict(self, viewer=None):
        d = {
            "id": self.id,
            "type": self.type,
            "sender": self.sender,
            "targets": self.targets,
            "content": self.content,
            "parent_pheromone_id": self.parent_pheromone_id,
            "judgment_status": self.judgment_status,
            "metadata": self.metadata,
            "visibility": self.visibility,
            "timestamp": self.timestamp
        }
        # 权限过滤：私有信息只对特定 EP 可见
        if self.visibility == "public":
            pass  # 所有人都能看到
        elif self.visibility == "private_to_sender":
            if viewer != self.sender:
                d["content"] = "[私有 - 仅发送者可见]"
        elif self.visibility == "private_to_target":
            if viewer not in self.targets:
                d["content"] = "[私有 - 仅目标可见]"
        elif self.visibility == "private_to_group":
            if viewer not in self.visible_to:
                d["content"] = "[私有 - 仅群组成员可见]"
        return d

# ============ 模拟数据 ============

PARTICIPANTS = {
    "employee_zeng": {"name": "增", "ep": "EP001", "role": "员工"},
    "boss_agent": {"name": "Boss Agent", "ep": "EP002", "role": "AI Agent"},
    "manager_peng": {"name": "彭老板", "ep": "EP003", "role": "老板"},
    "hr_li": {"name": "李HR", "ep": "EP004", "role": "HR"},
}

# 内存存储
pheromones = []
pending_responses = {}  # 用于模拟 Boss Agent 的响应

# ============ API 端点 ============

@app.route("/api/participants", methods=["GET"])
def get_participants():
    """获取所有参与者"""
    return jsonify(PARTICIPANTS)

@app.route("/api/pheromones", methods=["GET"])
def get_pheromones():
    """获取所有信息素"""
    viewer = request.args.get("viewer")  # 可选：按 viewer 过滤可见性
    return jsonify([p.to_dict(viewer) for p in pheromones])

@app.route("/api/pheromones", methods=["POST"])
def create_pheromone():
    """创建新的信息素"""
    data = request.json
    p = Pheromone(
        type=data.get("type"),
        sender=data.get("sender"),
        targets=data.get("targets", []),
        content=data.get("content"),
        parent_pheromone_id=data.get("parent_pheromone_id"),
        metadata=data.get("metadata", {}),
        visibility=data.get("visibility", "public"),
        visible_to=data.get("visible_to", [])
    )
    pheromones.append(p)

    # 触发后续处理
    if p.type == "weekly_report":
        handle_weekly_report(p)
    elif p.type == "approval":
        handle_approval(p)

    return jsonify(p.to_dict()), 201

@app.route("/api/pheromones/<pid>", methods=["GET"])
def get_pheromone(pid):
    """获取单条信息素"""
    viewer = request.args.get("viewer")
    for p in pheromones:
        if p.id == pid:
            return jsonify(p.to_dict(viewer))
    return jsonify({"error": "not found"}), 404

@app.route("/api/chain/<pid>", methods=["GET"])
def get_chain(pid):
    """获取信息素链路"""
    viewer = request.args.get("viewer")
    chain = []
    target_id = pid

    # 第一步：向上追溯（找 parent）
    while target_id:
        found = None
        for p in pheromones:
            if p.id == target_id:
                found = p
                break
        if found:
            chain.append(found.to_dict(viewer))
            target_id = found.parent_pheromone_id if found.parent_pheromone_id != found.id else None
        else:
            break

    # 第二步：向下查找（找 children/approvals）
    # 扫描所有 pheromone，把 parent_pheromone_id == pid 的追加进来
    for p in pheromones:
        if p.parent_pheromone_id == pid:
            chain.append(p.to_dict(viewer))
            # 递归获取子节点的子节点
            chain.extend(get_sub_chain(p.id, viewer))

    return jsonify(chain)

def get_sub_chain(pid, viewer=None):
    """递归获取子链路"""
    sub = []
    for p in pheromones:
        if p.parent_pheromone_id == pid:
            sub.append(p.to_dict(viewer))
            sub.extend(get_sub_chain(p.id, viewer))
    return sub

@app.route("/api/reset", methods=["POST"])
def reset():
    """重置数据"""
    global pheromones
    pheromones = []
    return jsonify({"status": "reset"})

# ============ 业务逻辑 ============

def handle_weekly_report(p):
    """处理周报：触发 Boss Agent 生成汇总"""
    digest = Pheromone(
        type="weekly_digest",
        sender="boss_agent",
        targets=["manager_peng", "hr_li"],
        content=generate_digest_content(),
        parent_pheromone_id=p.id,
        metadata={"source_report_id": p.id}
    )
    pheromones.append(digest)
    pending_responses[digest.id] = digest

def generate_digest_content():
    """生成周报汇总内容"""
    reports = [p for p in pheromones if p.type == "weekly_report"]
    count = len(reports)
    contents = [p.content for p in reports]

    summary = f"部门周报汇总：共{count}人提交。\n"
    for i, c in enumerate(contents):
        summary += f"- 周报{i+1}：{c}\n"
    summary += "请老板和HR审批。"

    return summary

def handle_approval(p):
    """处理审批：更新原始 pheromone 状态"""
    if p.parent_pheromone_id:
        for parent in pheromones:
            if parent.id == p.parent_pheromone_id:
                parent.judgment_status = p.judgment_status
                break

# ============ 前端页面 ============

@app.route("/")
def index():
    return """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Crew Demo - 周报聚合</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #0a0a0f;
            color: #e0e0e0;
            min-height: 100vh;
            padding: 40px;
        }
        h1 {
            text-align: center;
            font-size: 28px;
            font-weight: 600;
            margin-bottom: 8px;
            color: #fff;
        }
        .subtitle {
            text-align: center;
            color: #666;
            margin-bottom: 40px;
        }
        .container {
            max-width: 1000px;
            margin: 0 auto;
        }

        /* 信息流图 */
        .flow-diagram {
            background: #111118;
            border: 1px solid #222;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 30px;
        }
        .flow-title {
            font-size: 14px;
            color: #666;
            margin-bottom: 20px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .flow-nodes {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 20px;
            flex-wrap: wrap;
            margin-bottom: 30px;
        }
        .node {
            background: #1a1a24;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 12px 20px;
            text-align: center;
            min-width: 100px;
        }
        .node.agent { border-color: #6366f1; }
        .node.human { border-color: #22c55e; }
        .node-name { font-weight: 600; color: #fff; }
        .node-role { font-size: 12px; color: #666; margin-top: 4px; }

        .flow-arrow {
            color: #444;
            font-size: 20px;
        }

        .pheromone-line {
            display: flex;
            align-items: center;
            gap: 15px;
            padding: 15px;
            background: #16161e;
            border-radius: 8px;
            margin-bottom: 10px;
        }
        .pheromone-line.processed { opacity: 0.6; }
        .pheromone-badge {
            background: #6366f1;
            color: #fff;
            font-size: 11px;
            padding: 4px 8px;
            border-radius: 4px;
            font-family: monospace;
            min-width: 80px;
            text-align: center;
        }
        .pheromone-badge.private { background: #f59e0b; }
        .pheromone-content {
            flex: 1;
            font-size: 14px;
            color: #aaa;
        }
        .pheromone-status {
            font-size: 12px;
            padding: 4px 10px;
            border-radius: 4px;
        }
        .pheromone-status.pending { background: #fbbf24; color: #000; }
        .pheromone-status.approved { background: #22c55e; color: #000; }
        .pheromone-status.done { background: #333; color: #888; }

        /* 操作区 */
        .action-area {
            background: #111118;
            border: 1px solid #222;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 30px;
        }
        .action-title {
            font-size: 14px;
            color: #666;
            margin-bottom: 20px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-group label {
            display: block;
            font-size: 13px;
            color: #888;
            margin-bottom: 8px;
        }
        textarea {
            width: 100%;
            background: #1a1a24;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 12px;
            color: #e0e0e0;
            font-size: 14px;
            resize: vertical;
            min-height: 80px;
            font-family: inherit;
        }
        textarea:focus { outline: none; border-color: #6366f1; }
        button {
            background: #6366f1;
            color: #fff;
            border: none;
            border-radius: 8px;
            padding: 12px 24px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }
        button:hover { background: #5558e3; }
        button:disabled { background: #333; cursor: not-allowed; }

        /* 结果展示 */
        .result-area {
            background: #111118;
            border: 1px solid #222;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 30px;
        }
        .result-title {
            font-size: 14px;
            color: #666;
            margin-bottom: 20px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .chain-item {
            padding: 15px;
            background: #16161e;
            border-radius: 8px;
            margin-bottom: 10px;
            border-left: 3px solid #333;
        }
        .chain-item.pending { border-left-color: #fbbf24; }
        .chain-item.approved { border-left-color: #22c55e; }
        .chain-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 8px;
        }
        .chain-id { font-family: monospace; font-size: 12px; color: #6366f1; }
        .chain-type { font-size: 12px; color: #888; }
        .chain-body { font-size: 14px; color: #ccc; }
        .chain-meta { font-size: 12px; color: #555; margin-top: 8px; }
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #444;
        }

        /* 状态面板 */
        .status-panel {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin-bottom: 30px;
        }
        .status-card {
            background: #111118;
            border: 1px solid #222;
            border-radius: 8px;
            padding: 15px;
            text-align: center;
        }
        .status-number {
            font-size: 32px;
            font-weight: 700;
            color: #6366f1;
        }
        .status-label {
            font-size: 12px;
            color: #666;
            margin-top: 4px;
        }

        .reset-btn {
            background: transparent;
            border: 1px solid #333;
            color: #666;
            margin-left: 10px;
        }
        .reset-btn:hover { border-color: #6366f1; color: #6366f1; }

        /* 私有消息提示 */
        .private-hint {
            background: #f59e0b;
            color: #000;
            font-size: 11px;
            padding: 2px 6px;
            border-radius: 3px;
            margin-left: 8px;
        }

        /* 切换视图 */
        .viewer-switch {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        .viewer-btn {
            background: #1a1a24;
            border: 1px solid #333;
            color: #888;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            cursor: pointer;
        }
        .viewer-btn:hover { border-color: #6366f1; color: #6366f1; }
        .viewer-btn.active { background: #6366f1; border-color: #6366f1; color: #fff; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Crew Demo</h1>
        <p class="subtitle">信息自己知道去哪 · Pheromone 链演示</p>

        <!-- 状态面板 -->
        <div class="status-panel">
            <div class="status-card">
                <div class="status-number" id="total-count">0</div>
                <div class="status-label">总 Pheromone 数</div>
            </div>
            <div class="status-card">
                <div class="status-number" id="pending-count">0</div>
                <div class="status-label">待审批</div>
            </div>
            <div class="status-card">
                <div class="status-number" id="approved-count">0</div>
                <div class="status-label">已审批</div>
            </div>
            <div class="status-card">
                <div class="status-number" id="done-count">0</div>
                <div class="status-label">已完成</div>
            </div>
        </div>

        <!-- 信息流图 -->
        <div class="flow-diagram">
            <div class="flow-title">信息流图</div>
            <div class="flow-nodes">
                <div class="node human">
                    <div class="node-name">增</div>
                    <div class="node-role">员工</div>
                </div>
                <div class="flow-arrow">→</div>
                <div class="node agent">
                    <div class="node-name">Boss Agent</div>
                    <div class="node-role">AI 汇总</div>
                </div>
                <div class="flow-arrow">→</div>
                <div class="node human">
                    <div class="node-name">彭老板</div>
                    <div class="node-role">审批</div>
                </div>
                <div class="flow-arrow">→</div>
                <div class="node human">
                    <div class="node-name">李HR</div>
                    <div class="node-role">归档</div>
                </div>
            </div>

            <div id="pheromone-list">
                <div class="empty-state">暂无信息，等待提交周报...</div>
            </div>
        </div>

        <!-- 操作区 -->
        <div class="action-area">
            <div class="action-title">提交周报</div>
            <div class="form-group">
                <label>本周完成的工作</label>
                <textarea id="report-content" placeholder="例如：完成了用户访谈、整理了需求文档、协调了周会..."></textarea>
            </div>
            <div class="form-group">
                <label>隐私级别</label>
                <select id="report-visibility" style="background:#1a1a24;border:1px solid #333;border-radius:8px;padding:8px;color:#e0e0e0;font-size:14px;width:100%;">
                    <option value="public" selected>公开 - 所有人都能看见</option>
                    <option value="private_to_sender">私有 - 仅发送者可见</option>
                    <option value="private_to_target">私有 - 仅目标可见</option>
                    <option value="private_to_group">私有 - 仅群组成员可见</option>
                </select>
            </div>
            <button onclick="submitReport()">提交周报</button>
            <button class="reset-btn" onclick="resetDemo()">重置</button>
        </div>

        <!-- 链路追溯 -->
        <div class="result-area">
            <div class="action-title">链路追溯</div>
            <div class="viewer-switch">
                <span style="color:#666;font-size:13px;margin-right:10px;">模拟视角：</span>
                <button class="viewer-btn active" onclick="setViewer(null)">全局视图</button>
                <button class="viewer-btn" onclick="setViewer('employee_zeng')">增 (EP001)</button>
                <button class="viewer-btn" onclick="setViewer('boss_agent')">Boss Agent (EP002)</button>
                <button class="viewer-btn" onclick="setViewer('manager_peng')">彭老板 (EP003)</button>
                <button class="viewer-btn" onclick="setViewer('hr_li')">李HR (EP004)</button>
            </div>
            <div id="chain-list">
                <div class="empty-state">暂无链路，点击上方节点查看详情...</div>
            </div>
        </div>
    </div>

    <script>
        let currentViewer = null;

        function setViewer(viewer) {
            currentViewer = viewer;
            document.querySelectorAll('.viewer-btn').forEach(btn => {
                btn.classList.toggle('active', btn.textContent.includes(viewer || '全局'));
            });
            refresh();
        }

        async function submitReport() {
            const content = document.getElementById("report-content").value.trim();
            if (!content) {
                alert("请填写周报内容");
                return;
            }

            const visibility = document.getElementById("report-visibility").value;

            const btn = document.querySelector(".action-area button");
            btn.disabled = true;
            btn.textContent = "提交中...";

            try {
                const res = await fetch("/api/pheromones", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        type: "weekly_report",
                        sender: "employee_zeng",
                        targets: ["boss_agent"],
                        content: content,
                        visibility: visibility,
                        visible_to: visibility === "private_to_group" ? ["EP001", "EP002"] : []
                    })
                });

                if (res.ok) {
                    document.getElementById("report-content").value = "";
                    await refresh();
                }
            } catch (e) {
                console.error(e);
            } finally {
                btn.disabled = false;
                btn.textContent = "提交周报";
            }
        }

        async function approve(pheromoneId) {
            await fetch("/api/pheromones", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    type: "approval",
                    sender: "manager_peng",
                    targets: [pheromoneId],
                    content: "已阅",
                    parent_pheromone_id: pheromoneId,
                    judgment_status: "approved"
                })
            });
            await refresh();
        }

        async function refresh() {
            const viewerParam = currentViewer ? `?viewer=${currentViewer}` : "";
            const res = await fetch("/api/pheromones" + viewerParam);
            const data = await res.json();

            document.getElementById("total-count").textContent = data.length;
            document.getElementById("pending-count").textContent = data.filter(p => p.judgment_status === "pending").length;
            document.getElementById("approved-count").textContent = data.filter(p => p.judgment_status === "approved").length;
            document.getElementById("done-count").textContent = data.filter(p => p.type === "approval").length;

            const list = document.getElementById("pheromone-list");
            if (data.length === 0) {
                list.innerHTML = '<div class="empty-state">暂无信息，等待提交周报...</div>';
            } else {
                list.innerHTML = data.map(p => {
                    const statusClass = p.judgment_status === "pending" ? "pending" : "approved";
                    const statusText = p.judgment_status === "pending" ? "待审批" : "已审批";
                    const isProcessed = p.type === "approval";
                    const isPrivate = p.visibility !== "public";
                    const badgeClass = isPrivate ? "pheromone-badge private" : "pheromone-badge";
                    const privateHint = isPrivate ? `<span class="private-hint">${p.visibility}</span>` : "";
                    return `
                        <div class="pheromone-line ${isProcessed ? 'processed' : ''}">
                            <div class="${badgeClass}">${p.type}${privateHint}</div>
                            <div class="pheromone-content">${p.content}</div>
                            <div>
                                <span class="pheromone-status ${statusClass}">${statusText}</span>
                                ${p.judgment_status === "pending" && p.type !== "approval" ? `<button class="approve-btn" onclick="approve('${p.id}')" style="margin-left:10px;padding:4px 12px;font-size:12px;background:#22c55e;color:#000;border:none;border-radius:4px;cursor:pointer">批准</button>` : ''}
                            </div>
                        </div>
                    `;
                }).join("");
            }
        }

        async function resetDemo() {
            await fetch("/api/reset", {method: "POST"});
            await refresh();
        }

        refresh();
    </script>
</body>
</html>
    """