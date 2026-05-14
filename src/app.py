"""
Crew Demo - 周报聚合场景
最小可演示版本 v0.4

新增：
- visibility 字段（public | private_to_sender | private_to_target | private_to_group）
- Agent Profile（借鉴 AgentBridge 的主人认知 Profile）
- Pheromone 反馈学习（借鉴 Moxt 的共享记忆——所有 Agent 都学到）

run: python src/app.py
"""
from flask import Flask, jsonify, request
from datetime import datetime
import uuid

app = Flask(__name__)

# ============ Agent Profile（借鉴 AgentBridge） ============

class AgentProfile:
    """Agent 的认知 Profile——让 Agent 知道自己是谁、该以什么角度响应"""
    def __init__(self, agent_id, name, ep, role, judgment_criteria=None, peer_eps=None, specialty=None):
        self.agent_id = agent_id
        self.name = name
        self.ep = ep
        self.role = role
        self.judgment_criteria = judgment_criteria or []
        self.peer_eps = peer_eps or []
        self.specialty = specialty or ""
        self.learned_patterns = []  # 从反馈中学到的 pattern（借鉴 Moxt）

    def add_learned(self, pattern):
        """从反馈中学习"""
        for p in self.learned_patterns:
            if p["pattern"] == pattern:
                p["count"] += 1
                return
        self.learned_patterns.append({"pattern": pattern, "count": 1})

    def to_dict(self):
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "ep": self.ep,
            "role": self.role,
            "judgment_criteria": self.judgment_criteria,
            "peer_eps": self.peer_eps,
            "specialty": self.specialty,
            "learned_patterns": self.learned_patterns
        }

# 预定义的 Agent Profiles
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

# ============ Pheromone 反馈学习（借鉴 Moxt） ============

# 内存存储：反馈记录
feedbacks = []

# 全局学习统计（Moxt 的"纠正一个 Agent 的错误，所有 Agent 都学到"）
GLOBAL_LEARNINGS = {
    "useful_patterns": [],
    "unclear_patterns": [],
}

def learn_from_feedback(sender_id, feedback_type, content):
    """从反馈中学习——更新全局学习统计 + 单个 Agent Profile"""
    # 1. 更新全局学习统计
    pattern_key = f"{sender_id}_{feedback_type}"
    if feedback_type == "useful":
        found = False
        for p in GLOBAL_LEARNINGS["useful_patterns"]:
            if p["pattern"] == pattern_key:
                p["count"] += 1
                found = True
                break
        if not found:
            GLOBAL_LEARNINGS["useful_patterns"].append({
                "pattern": pattern_key,
                "count": 1,
                "from_agent": sender_id
            })
    elif feedback_type == "unclear":
        GLOBAL_LEARNINGS["unclear_patterns"].append({
            "pattern": pattern_key,
            "count": 1,
            "from_agent": sender_id
        })

    # 2. 更新单个 Agent Profile（借鉴 Moxt：所有 Agent 都学到）
    profile = AGENT_PROFILES.get(sender_id)
    if profile:
        # 提取内容关键词作为 pattern
        keywords = content.split("：")[1][:20] if "：" in content else content[:20]
        profile.add_learned(keywords)

def get_learned_for_agent(agent_id):
    """获取某个 Agent 学到的内容"""
    profile = AGENT_PROFILES.get(agent_id)
    if not profile:
        return {}

    return {
        "learned_patterns": profile.learned_patterns,
        "global_useful": [
            p for p in GLOBAL_LEARNINGS["useful_patterns"]
            if p.get("from_agent") == agent_id
        ],
        "global_unclear": [
            p for p in GLOBAL_LEARNINGS["unclear_patterns"]
            if p.get("from_agent") == agent_id
        ]
    }

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
        self.visibility = visibility
        self.visible_to = visible_to or []
        self.timestamp = datetime.utcnow().isoformat() + "Z"
        self.feedback_given = []  # 记录谁给过反馈

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
        # 权限过滤
        if self.visibility == "public":
            pass
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
pending_responses = {}

# ============ API 端点 ============

@app.route("/api/participants", methods=["GET"])
def get_participants():
    return jsonify(PARTICIPANTS)

@app.route("/api/agents/profiles", methods=["GET"])
def get_agent_profiles():
    return jsonify({k: v.to_dict() for k, v in AGENT_PROFILES.items()})

@app.route("/api/agents/profiles/<agent_id>", methods=["GET"])
def get_agent_profile(agent_id):
    if agent_id in AGENT_PROFILES:
        # 合并学习到的内容
        result = AGENT_PROFILES[agent_id].to_dict()
        result["learned"] = get_learned_for_agent(agent_id)
        return jsonify(result)
    return jsonify({"error": "not found"}), 404

@app.route("/api/agents/profiles/<agent_id>", methods=["PUT"])
def update_agent_profile(agent_id):
    if agent_id not in AGENT_PROFILES:
        return jsonify({"error": "not found"}), 404
    data = request.json
    profile = AGENT_PROFILES[agent_id]
    if "judgment_criteria" in data:
        profile.judgment_criteria = data["judgment_criteria"]
    if "peer_eps" in data:
        profile.peer_eps = data["peer_eps"]
    if "specialty" in data:
        profile.specialty = data["specialty"]
    return jsonify(profile.to_dict())

@app.route("/api/pheromones", methods=["GET"])
def get_pheromones():
    viewer = request.args.get("viewer")
    return jsonify([p.to_dict(viewer) for p in pheromones])

@app.route("/api/pheromones", methods=["POST"])
def create_pheromone():
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

    if p.type == "weekly_report":
        handle_weekly_report(p)
    elif p.type == "approval":
        handle_approval(p)
    elif p.type == "feedback":
        handle_feedback(p)

    return jsonify(p.to_dict()), 201

@app.route("/api/pheromones/<pid>", methods=["GET"])
def get_pheromone(pid):
    viewer = request.args.get("viewer")
    for p in pheromones:
        if p.id == pid:
            return jsonify(p.to_dict(viewer))
    return jsonify({"error": "not found"}), 404

@app.route("/api/pheromones/<pid>/feedback", methods=["POST"])
def add_feedback(pid):
    """对 Pheromone 添加反馈"""
    data = request.json
    feedback_type = data.get("feedback_type")  # useful | not_useful | unclear
    sender_id = data.get("sender")

    for p in pheromones:
        if p.id == pid:
            p.feedback_given.append({
                "from": sender_id,
                "type": feedback_type,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })
            # 学习：借鉴 Moxt 的"纠正一个 Agent 的错误，所有 Agent 都学到"
            learn_from_feedback(sender_id, feedback_type, p.content)
            return jsonify({"status": "ok", "learned": get_learned_for_agent(sender_id)})

    return jsonify({"error": "not found"}), 404

@app.route("/api/learnings", methods=["GET"])
def get_global_learnings():
    """获取全局学习统计"""
    return jsonify(GLOBAL_LEARNINGS)

@app.route("/api/chain/<pid>", methods=["GET"])
def get_chain(pid):
    viewer = request.args.get("viewer")
    chain = []
    target_id = pid

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

    for p in pheromones:
        if p.parent_pheromone_id == pid:
            chain.append(p.to_dict(viewer))
            chain.extend(get_sub_chain(p.id, viewer))

    return jsonify(chain)

def get_sub_chain(pid, viewer=None):
    sub = []
    for p in pheromones:
        if p.parent_pheromone_id == pid:
            sub.append(p.to_dict(viewer))
            sub.extend(get_sub_chain(p.id, viewer))
    return sub

@app.route("/api/reset", methods=["POST"])
def reset():
    global pheromones, feedbacks, GLOBAL_LEARNINGS
    pheromones = []
    feedbacks = []
    GLOBAL_LEARNINGS = {"useful_patterns": [], "unclear_patterns": []}
    # 重置 Agent Profile 的学习记录
    for profile in AGENT_PROFILES.values():
        profile.learned_patterns = []
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
            "judgment_criteria": boss_profile.judgment_criteria if boss_profile else [],
            "peer_eps": boss_profile.peer_eps if boss_profile else []
        }
    )
    pheromones.append(digest)
    pending_responses[digest.id] = digest

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

def handle_feedback(p):
    """处理反馈 Pheromone"""
    feedback_type = p.metadata.get("feedback_type")
    if feedback_type and p.sender:
        learn_from_feedback(p.sender, feedback_type, p.content)

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
            max-width: 1100px;
            margin: 0 auto;
        }

        .flow-diagram, .action-area, .result-area, .profile-area, .learning-area {
            background: #111118;
            border: 1px solid #222;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 30px;
        }
        .flow-title, .action-title, .result-title {
            font-size: 14px;
            color: #666;
            margin-bottom: 20px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

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
        .pheromone-badge.feedback { background: #ec4899; }
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

        .form-group { margin-bottom: 20px; }
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
        select {
            width: 100%;
            background: #1a1a24;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 8px;
            color: #e0e0e0;
            font-size: 14px;
        }
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
        .reset-btn {
            background: transparent;
            border: 1px solid #333;
            color: #666;
            margin-left: 10px;
        }
        .reset-btn:hover { border-color: #6366f1; color: #6366f1; }

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

        .profile-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
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
        .profile-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
        }
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
        .profile-tag.learned { border-color: #ec4899; color: #ec4899; }

        .learning-section {
            background: #16161e;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 15px;
        }
        .learning-title { font-size: 14px; color: #fff; margin-bottom: 10px; }
        .learning-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 0;
            border-bottom: 1px solid #222;
        }
        .learning-item:last-child { border-bottom: none; }
        .learning-count {
            background: #6366f1;
            color: #fff;
            font-size: 12px;
            padding: 2px 8px;
            border-radius: 4px;
            font-family: monospace;
        }
        .learning-from { font-size: 12px; color: #555; }

        .feedback-btn {
            padding: 4px 10px;
            font-size: 11px;
            border-radius: 4px;
            border: none;
            cursor: pointer;
            margin-left: 5px;
        }
        .feedback-btn.useful { background: #22c55e; color: #000; }
        .feedback-btn.unclear { background: #f59e0b; color: #000; }

        .empty-state {
            text-align: center;
            padding: 40px 20px;
            color: #444;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Crew Demo</h1>
        <p class="subtitle">信息自己知道去哪 · Pheromone 链演示</p>

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
                <div class="status-number" id="learned-count">0</div>
                <div class="status-label">学习次数</div>
            </div>
        </div>

        <div class="profile-area">
            <div class="flow-title">Agent Profile · 认知 Profile</div>
            <div class="profile-grid" id="profile-grid">
                <div class="empty-state">加载中...</div>
            </div>
        </div>

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

        <div class="action-area">
            <div class="action-title">提交周报</div>
            <div class="form-group">
                <label>本周完成的工作</label>
                <textarea id="report-content" placeholder="例如：完成了用户访谈、整理了需求文档..."></textarea>
            </div>
            <div class="form-group">
                <label>隐私级别</label>
                <select id="report-visibility">
                    <option value="public" selected>公开</option>
                    <option value="private_to_sender">私有 - 仅发送者可见</option>
                    <option value="private_to_target">私有 - 仅目标可见</option>
                    <option value="private_to_group">私有 - 群组成员可见</option>
                </select>
            </div>
            <button onclick="submitReport()">提交周报</button>
            <button class="reset-btn" onclick="resetDemo()">重置</button>
        </div>

        <div class="learning-area">
            <div class="flow-title">全局学习统计（Moxt 借鉴：所有 Agent 都学到）</div>
            <div class="learning-section">
                <div class="learning-title">有用的 Pattern</div>
                <div id="useful-patterns">
                    <div class="empty-state">暂无</div>
                </div>
            </div>
            <div class="learning-section">
                <div class="learning-title">被标记为"不理解"的 Pattern</div>
                <div id="unclear-patterns">
                    <div class="empty-state">暂无</div>
                </div>
            </div>
        </div>

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
                <div class="empty-state">暂无链路...</div>
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
                await fetch("/api/pheromones", {
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
                document.getElementById("report-content").value = "";
                await refresh();
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

        async function giveFeedback(pheromoneId, feedbackType) {
            await fetch(`/api/pheromones/${pheromoneId}/feedback`, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    sender: currentViewer || "manager_peng",
                    feedback_type: feedbackType
                })
            });
            await loadLearning();
        }

        async function loadLearning() {
            const res = await fetch("/api/learnings");
            const data = await res.json();

            const useful = document.getElementById("useful-patterns");
            if (data.useful_patterns.length === 0) {
                useful.innerHTML = '<div class="empty-state">暂无</div>';
            } else {
                useful.innerHTML = data.useful_patterns.map(p => `
                    <div class="learning-item">
                        <span class="learning-count">${p.count}</span>
                        <span>${p.pattern}</span>
                        <span class="learning-from">from ${p.from_agent}</span>
                    </div>
                `).join("");
            }

            const unclear = document.getElementById("unclear-patterns");
            if (data.unclear_patterns.length === 0) {
                unclear.innerHTML = '<div class="empty-state">暂无</div>';
            } else {
                unclear.innerHTML = data.unclear_patterns.map(p => `
                    <div class="learning-item">
                        <span class="learning-count" style="background:#f59e0b">${p.count}</span>
                        <span>${p.pattern}</span>
                        <span class="learning-from">from ${p.from_agent}</span>
                    </div>
                `).join("");
            }

            // 更新学习次数
            const total = data.useful_patterns.length + data.unclear_patterns.length;
            document.getElementById("learned-count").textContent = total;
        }

        async function refresh() {
            const viewerParam = currentViewer ? `?viewer=${currentViewer}` : "";
            const res = await fetch("/api/pheromones" + viewerParam);
            const data = await res.json();

            document.getElementById("total-count").textContent = data.length;
            document.getElementById("pending-count").textContent = data.filter(p => p.judgment_status === "pending").length;
            document.getElementById("approved-count").textContent = data.filter(p => p.judgment_status === "approved").length;

            const list = document.getElementById("pheromone-list");
            if (data.length === 0) {
                list.innerHTML = '<div class="empty-state">暂无信息，等待提交周报...</div>';
            } else {
                list.innerHTML = data.map(p => {
                    const statusClass = p.judgment_status === "pending" ? "pending" : "approved";
                    const statusText = p.judgment_status === "pending" ? "待审批" : "已审批";
                    const isProcessed = p.type === "approval";
                    const isPrivate = p.visibility !== "public";
                    const isFeedback = p.type === "feedback";
                    let badgeClass = "pheromone-badge";
                    if (isPrivate) badgeClass += " private";
                    if (isFeedback) badgeClass += " feedback";
                    const privateHint = isPrivate ? `<span class="private-hint">${p.visibility}</span>` : "";
                    return `
                        <div class="pheromone-line ${isProcessed ? 'processed' : ''}">
                            <div class="${badgeClass}">${p.type}${privateHint}</div>
                            <div class="pheromone-content">${p.content}</div>
                            <div>
                                <span class="pheromone-status ${statusClass}">${statusText}</span>
                                ${p.judgment_status === "pending" && p.type === "weekly_digest" ? `
                                    <button class="approve-btn" onclick="approve('${p.id}')" style="margin-left:10px;padding:4px 12px;font-size:12px;background:#22c55e;color:#000;border:none;border-radius:4px;cursor:pointer">批准</button>
                                    <button class="feedback-btn useful" onclick="giveFeedback('${p.id}', 'useful')" title="有用">✓</button>
                                    <button class="feedback-btn unclear" onclick="giveFeedback('${p.id}', 'unclear')" title="不理解">?</button>
                                ` : ''}
                            </div>
                        </div>
                    `;
                }).join("");
            }

            await loadLearning();
        }

        async function loadProfiles() {
            const res = await fetch("/api/agents/profiles");
            const data = await res.json();
            const grid = document.getElementById("profile-grid");
            grid.innerHTML = Object.entries(data).map(([id, profile]) => {
                const cardClass = profile.role === "AI Agent" ? "agent" : "human";
                const avatar = profile.name[0];
                const criteria = (profile.judgment_criteria || []).map(c =>
                    `<span class="profile-tag criteria">${c}</span>`
                ).join("");
                const peers = (profile.peer_eps || []).map(p =>
                    `<span class="profile-tag peer">${p}</span>`
                ).join("");
                const learned = (profile.learned_patterns || []).map(l =>
                    `<span class="profile-tag learned">${l.pattern} (${l.count})</span>`
                ).join("");
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
                            <div class="profile-section-title">已学到的 Pattern</div>
                            ${learned || "<span class='profile-tag'>暂无</span>"}
                        </div>
                        <div class="profile-section">
                            <div class="profile-section-title">需要对齐的 EP</div>
                            ${peers || "<span class='profile-tag'>无</span>"}
                        </div>
                    </div>
                `;
            }).join("");
        }

        async function resetDemo() {
            await fetch("/api/reset", {method: "POST"});
            await refresh();
            await loadProfiles();
            await loadLearning();
        }

        refresh();
        loadProfiles();
        loadLearning();
    </script>
</body>
</html>
    """