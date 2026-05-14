"""
Crew Demo - 周报聚合场景
最小可演示版本 v1.0 精简版

保留核心：
- Pheromone 链（parent + children）
- Agent Profile（Boss Agent 用它生成 digest）
- Boss Agent 主动创建 Task
- 链路追溯

删除（过度工程）：
- visibility 权限控制
- 反馈学习 + 全局学习展示
- 内容质量评分
- Task resolve 流程

run: python src/app.py
"""
from flask import Flask, jsonify, request
from datetime import datetime
import uuid

app = Flask(__name__)

# ============ Agent Profile ============

class AgentProfile:
    def __init__(self, agent_id, name, ep, role, judgment_criteria=None, peer_eps=None, specialty=None):
        self.agent_id = agent_id
        self.name = name
        self.ep = ep
        self.role = role
        self.judgment_criteria = judgment_criteria or []
        self.peer_eps = peer_eps or []
        self.specialty = specialty or ""

    def to_dict(self):
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "ep": self.ep,
            "role": self.role,
            "judgment_criteria": self.judgment_criteria,
            "peer_eps": self.peer_eps,
            "specialty": self.specialty
        }

AGENT_PROFILES = {
    "employee_zeng": AgentProfile(
        agent_id="employee_zeng",
        name="增",
        ep="EP001",
        role="员工",
        specialty="用户研究、产品设计",
        judgment_criteria=["需求是否真实", "用户是否需要"],
        peer_eps=["EP002", "EP003"]
    ),
    "boss_agent": AgentProfile(
        agent_id="boss_agent",
        name="Boss Agent",
        ep="EP002",
        role="AI Agent",
        specialty="团队协调、资源调配",
        judgment_criteria=["是否符合团队目标", "优先级是否合理", "资源是否够用"],
        peer_eps=["EP001", "EP003", "EP004"]
    ),
    "manager_peng": AgentProfile(
        agent_id="manager_peng",
        name="彭老板",
        ep="EP003",
        role="老板",
        specialty="战略决策、团队管理",
        judgment_criteria=["是否对公司有利", "风险是否可控", "ROI 是否合理"],
        peer_eps=["EP002"]
    ),
    "hr_li": AgentProfile(
        agent_id="hr_li",
        name="李HR",
        ep="EP004",
        role="HR",
        specialty="人力资源、政策合规",
        judgment_criteria=["是否合规", "是否公平", "是否可持续"],
        peer_eps=["EP002", "EP003"]
    ),
}

# ============ 数据模型 ============

class Pheromone:
    def __init__(self, id=None, type=None, sender=None, targets=None, content=None,
                 parent_pheromone_id=None, judgment_status="pending", metadata=None):
        self.id = id or str(uuid.uuid4())[:8]
        self.type = type
        self.sender = sender
        self.targets = targets or []
        self.content = content
        self.parent_pheromone_id = parent_pheromone_id
        self.judgment_status = judgment_status
        self.metadata = metadata or {}
        self.timestamp = datetime.utcnow().isoformat() + "Z"

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "sender": self.sender,
            "targets": self.targets,
            "content": self.content,
            "parent_pheromone_id": self.parent_pheromone_id,
            "judgment_status": self.judgment_status,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }

# ============ 存储 ============

PARTICIPANTS = {
    "employee_zeng": {"name": "增", "ep": "EP001", "role": "员工"},
    "boss_agent": {"name": "Boss Agent", "ep": "EP002", "role": "AI Agent"},
    "manager_peng": {"name": "彭老板", "ep": "EP003", "role": "老板"},
    "hr_li": {"name": "李HR", "ep": "EP004", "role": "HR"},
}

pheromones = []

# ============ API ============

@app.route("/api/participants", methods=["GET"])
def get_participants():
    return jsonify(PARTICIPANTS)

@app.route("/api/agents/profiles", methods=["GET"])
def get_agent_profiles():
    return jsonify({k: v.to_dict() for k, v in AGENT_PROFILES.items()})

@app.route("/api/agents/<agent_id>/create_task", methods=["POST"])
def agent_create_task(agent_id):
    """Agent 主动创建 Task（借鉴 Multica）"""
    if agent_id not in AGENT_PROFILES:
        return jsonify({"error": "agent not found"}), 404

    data = request.json
    p = Pheromone(
        type=data.get("task_type", "task"),
        sender=agent_id,
        targets=data.get("targets", []),
        content=data.get("content"),
        metadata={
            "priority": data.get("priority", "medium"),
            "created_by_agent": agent_id,
            "agent_profile": AGENT_PROFILES[agent_id].to_dict()
        }
    )
    pheromones.append(p)

    return jsonify({"status": "created", "pheromone": p.to_dict()}), 201

@app.route("/api/pheromones", methods=["GET"])
def get_pheromones():
    return jsonify([p.to_dict() for p in pheromones])

@app.route("/api/pheromones", methods=["POST"])
def create_pheromone():
    data = request.json
    p = Pheromone(
        type=data.get("type"),
        sender=data.get("sender"),
        targets=data.get("targets", []),
        content=data.get("content"),
        parent_pheromone_id=data.get("parent_pheromone_id"),
        metadata=data.get("metadata", {})
    )
    pheromones.append(p)

    if p.type == "weekly_report":
        handle_weekly_report(p)
    elif p.type == "approval":
        handle_approval(p)

    return jsonify(p.to_dict()), 201

@app.route("/api/pheromones/<pid>", methods=["GET"])
def get_pheromone(pid):
    for p in pheromones:
        if p.id == pid:
            return jsonify(p.to_dict())
    return jsonify({"error": "not found"}), 404

@app.route("/api/chain/<pid>", methods=["GET"])
def get_chain(pid):
    chain = []
    target_id = pid

    while target_id:
        found = None
        for p in pheromones:
            if p.id == target_id:
                found = p
                break
        if found:
            chain.append(found.to_dict())
            target_id = found.parent_pheromone_id if found.parent_pheromone_id != found.id else None
        else:
            break

    for p in pheromones:
        if p.parent_pheromone_id == pid:
            chain.append(p.to_dict())
            chain.extend(get_sub_chain(p.id))

    return jsonify(chain)

def get_sub_chain(pid):
    sub = []
    for p in pheromones:
        if p.parent_pheromone_id == pid:
            sub.append(p.to_dict())
            sub.extend(get_sub_chain(p.id))
    return sub

@app.route("/api/reset", methods=["POST"])
def reset():
    global pheromones
    pheromones = []
    return jsonify({"status": "reset"})

# ============ 业务逻辑 ============

def handle_weekly_report(p):
    boss_profile = AGENT_PROFILES.get("boss_agent")

    digest = Pheromone(
        type="weekly_digest",
        sender="boss_agent",
        targets=["manager_peng", "hr_li"],
        content=generate_digest_content(),
        parent_pheromone_id=p.id,
        metadata={
            "source_report_id": p.id,
            "judging_agent": "boss_agent",
            "judgment_criteria": boss_profile.judgment_criteria if boss_profile else []
        }
    )
    pheromones.append(digest)

def generate_digest_content():
    reports = [p for p in pheromones if p.type == "weekly_report"]
    count = len(reports)
    contents = [p.content for p in reports]

    summary = f"部门周报汇总：共{count}人提交。\n"
    for i, c in enumerate(contents):
        summary += f"- 周报{i+1}：{c}\n"
    summary += "请老板和HR审批。"

    return summary

def handle_approval(p):
    if p.parent_pheromone_id:
        for parent in pheromones:
            if parent.id == p.parent_pheromone_id:
                parent.judgment_status = p.judgment_status
                break

# ============ 前端 ============

@app.route("/")
def index():
    return """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Crew Demo</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #0a0a0f;
            color: #e0e0e0;
            min-height: 100vh;
            padding: 40px;
        }
        h1 { text-align: center; font-size: 28px; font-weight: 600; margin-bottom: 8px; color: #fff; }
        .subtitle { text-align: center; color: #666; margin-bottom: 40px; }
        .container { max-width: 900px; margin: 0 auto; }

        .card {
            background: #111118;
            border: 1px solid #222;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 30px;
        }
        .card-title {
            font-size: 14px;
            color: #666;
            margin-bottom: 20px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .status-panel {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
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
        .status-number { font-size: 32px; font-weight: 700; color: #6366f1; }
        .status-label { font-size: 12px; color: #666; margin-top: 4px; }

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

        .pheromone-line {
            display: flex;
            align-items: center;
            gap: 15px;
            padding: 15px;
            background: #16161e;
            border-radius: 8px;
            margin-bottom: 10px;
        }
        .pheromone-badge {
            background: #6366f1;
            color: #fff;
            font-size: 11px;
            padding: 4px 8px;
            border-radius: 4px;
            font-family: monospace;
            min-width: 90px;
            text-align: center;
        }
        .pheromone-badge.task { background: #8b5cf6; }
        .pheromone-badge.issue { background: #ef4444; }
        .pheromone-content { flex: 1; font-size: 14px; color: #aaa; }
        .pheromone-status { font-size: 12px; padding: 4px 10px; border-radius: 4px; }
        .pheromone-status.pending { background: #fbbf24; color: #000; }
        .pheromone-status.approved { background: #22c55e; color: #000; }

        .form-group { margin-bottom: 20px; }
        .form-group label { display: block; font-size: 13px; color: #888; margin-bottom: 8px; }
        textarea, input[type="text"], select {
            width: 100%;
            background: #1a1a24;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 12px;
            color: #e0e0e0;
            font-size: 14px;
            font-family: inherit;
        }
        textarea:focus, input:focus { outline: none; border-color: #6366f1; }
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
        .btn-secondary {
            background: transparent;
            border: 1px solid #333;
            color: #888;
        }
        .btn-secondary:hover { border-color: #6366f1; color: #6366f1; }
        .btn-agent { background: #8b5cf6; }
        .btn-agent:hover { background: #7c3aed; }
        .btn-small { padding: 6px 12px; font-size: 12px; }

        .profile-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 15px;
        }
        .profile-card {
            background: #16161e;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 15px;
        }
        .profile-card.agent { border-left: 3px solid #6366f1; }
        .profile-card.human { border-left: 3px solid #22c55e; }
        .profile-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
        .profile-avatar {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            background: #1a1a24;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 16px;
        }
        .profile-info { flex: 1; }
        .profile-name { font-weight: 600; color: #fff; font-size: 14px; }
        .profile-role { font-size: 12px; color: #666; }
        .profile-ep { font-size: 11px; color: #555; font-family: monospace; }
        .profile-section { margin-top: 10px; }
        .profile-section-title {
            font-size: 11px;
            color: #555;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 6px;
        }
        .profile-tag {
            display: inline-block;
            background: #1a1a24;
            border: 1px solid #333;
            border-radius: 4px;
            padding: 3px 8px;
            font-size: 12px;
            color: #888;
            margin: 2px;
        }
        .profile-tag.criteria { border-color: #6366f1; color: #6366f1; }
        .profile-tag.peer { border-color: #22c55e; color: #22c55e; }
        .profile-tag.specialty { border-color: #f59e0b; color: #f59e0b; }

        .task-section {
            background: #1a1a24;
            border: 1px dashed #8b5cf6;
            border-radius: 8px;
            padding: 20px;
            margin-top: 20px;
        }
        .task-section-title {
            font-size: 13px;
            color: #8b5cf6;
            margin-bottom: 15px;
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
        .chain-header { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
        .chain-id { font-family: monospace; font-size: 12px; color: #6366f1; }
        .chain-body { font-size: 14px; color: #ccc; }
        .chain-meta { font-size: 12px; color: #555; margin-top: 8px; }

        .empty-state { text-align: center; padding: 40px 20px; color: #444; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Crew Demo</h1>
        <p class="subtitle">信息自己知道去哪 · Pheromone 链演示</p>

        <div class="status-panel">
            <div class="status-card">
                <div class="status-number" id="total-count">0</div>
                <div class="status-label">总 Pheromone</div>
            </div>
            <div class="status-card">
                <div class="status-number" id="pending-count">0</div>
                <div class="status-label">待审批</div>
            </div>
            <div class="status-card">
                <div class="status-number" id="approved-count">0</div>
                <div class="status-label">已审批</div>
            </div>
        </div>

        <div class="card">
            <div class="card-title">Agent Profile</div>
            <div class="profile-grid" id="profile-grid">
                <div class="empty-state">加载中...</div>
            </div>
        </div>

        <div class="card">
            <div class="card-title">信息流图</div>
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
                <div class="empty-state">暂无信息...</div>
            </div>
        </div>

        <div class="card">
            <div class="card-title">提交周报</div>
            <div class="form-group">
                <label>本周完成的工作</label>
                <textarea id="report-content" placeholder="例如：完成了用户访谈、整理了需求文档..."></textarea>
            </div>
            <button onclick="submitReport()">提交周报</button>
            <button class="btn-secondary" onclick="resetDemo()">重置</button>
        </div>

        <div class="card">
            <div class="card-title">Agent 主动创建 Task（借鉴 Multica）</div>
            <div class="task-section">
                <div class="task-section-title">Boss Agent 发现问题时可以主动创建 Task</div>
                <div class="form-group">
                    <label>任务内容</label>
                    <input type="text" id="task-content" placeholder="例如：周报提交率偏低，建议提醒未提交人员">
                </div>
                <div class="form-group">
                    <label>类型</label>
                    <select id="task-type">
                        <option value="task">任务</option>
                        <option value="issue">问题</option>
                    </select>
                </div>
                <button class="btn-agent" onclick="createTask()">Boss Agent 创建任务</button>
            </div>
        </div>

        <div class="card">
            <div class="card-title">链路追溯</div>
            <div id="chain-list">
                <div class="empty-state">暂无链路...</div>
            </div>
        </div>
    </div>

    <script>
        async function submitReport() {
            const content = document.getElementById("report-content").value.trim();
            if (!content) { alert("请填写周报内容"); return; }
            const btn = document.querySelector(".card:nth-child(4) button");
            btn.disabled = true;

            try {
                await fetch("/api/pheromones", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        type: "weekly_report",
                        sender: "employee_zeng",
                        targets: ["boss_agent"],
                        content: content
                    })
                });
                document.getElementById("report-content").value = "";
                await refresh();
            } finally {
                btn.disabled = false;
            }
        }

        async function createTask() {
            const content = document.getElementById("task-content").value.trim();
            if (!content) { alert("请填写任务内容"); return; }

            await fetch("/api/agents/boss_agent/create_task", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    content: content,
                    task_type: document.getElementById("task-type").value,
                    targets: ["manager_peng"]
                })
            });

            document.getElementById("task-content").value = "";
            await refresh();
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
            const res = await fetch("/api/pheromones");
            const data = await res.json();

            document.getElementById("total-count").textContent = data.length;
            document.getElementById("pending-count").textContent = data.filter(p => p.judgment_status === "pending").length;
            document.getElementById("approved-count").textContent = data.filter(p => p.judgment_status === "approved").length;

            const list = document.getElementById("pheromone-list");
            if (data.length === 0) {
                list.innerHTML = '<div class="empty-state">暂无信息...</div>';
            } else {
                list.innerHTML = data.map(p => {
                    const statusClass = p.judgment_status === "pending" ? "pending" : "approved";
                    const statusText = p.judgment_status === "pending" ? "待审批" : "已审批";
                    let badgeClass = "pheromone-badge";
                    if (p.type === 'task') badgeClass += " task";
                    else if (p.type === 'issue') badgeClass += " issue";
                    return `
                        <div class="pheromone-line">
                            <div class="${badgeClass}">${p.type}</div>
                            <div class="pheromone-content">${p.content}</div>
                            <div>
                                <span class="pheromone-status ${statusClass}">${statusText}</span>
                                ${p.judgment_status === "pending" && p.type === "weekly_digest" ? `
                                    <button onclick="approve('${p.id}')" style="margin-left:10px;padding:4px 12px;font-size:12px;background:#22c55e;color:#000;border:none;border-radius:4px;cursor:pointer">批准</button>
                                ` : ''}
                            </div>
                        </div>
                    `;
                }).join("");
            }
        }

        async function loadProfiles() {
            const res = await fetch("/api/agents/profiles");
            const data = await res.json();
            const grid = document.getElementById("profile-grid");
            grid.innerHTML = Object.entries(data).map(([id, profile]) => {
                const cardClass = profile.role === "AI Agent" ? "agent" : "human";
                const avatar = profile.name[0];
                const criteria = (profile.judgment_criteria || []).map(c => `<span class="profile-tag criteria">${c}</span>`).join("");
                const peers = (profile.peer_eps || []).map(p => `<span class="profile-tag peer">${p}</span>`).join("");
                return `
                    <div class="profile-card ${cardClass}">
                        <div class="profile-header">
                            <div class="profile-avatar">${avatar}</div>
                            <div class="profile-info">
                                <div class="profile-name">${profile.name}</div>
                                <div class="profile-role">${profile.role}</div>
                                <div class="profile-ep">${profile.ep}</div>
                            </div>
                        </div>
                        <div class="profile-section">
                            <div class="profile-section-title">专长</div>
                            <span class="profile-tag specialty">${profile.specialty || "无"}</span>
                        </div>
                        <div class="profile-section">
                            <div class="profile-section-title">判断标准</div>
                            ${criteria || "<span class='profile-tag'>无</span>"}
                        </div>
                        <div class="profile-section">
                            <div class="profile-section-title">需要对齐</div>
                            ${peers || "<span class='profile-tag'>无</span>"}
                        </div>
                    </div>
                `;
            }).join("");
        }

        async function resetDemo() {
            await fetch("/api/reset", {method: "POST"});
            await refresh();
        }

        Promise.all([refresh(), loadProfiles()]);
    </script>
</body>
</html>
    """