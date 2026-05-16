"""
Crew Demo - Pheromone 通用框架
最小可运行版本 · 零硬编码

run: python src/app.py
"""
from flask import Flask, jsonify, request
from datetime import datetime
import uuid
import threading
import json
import os

app = Flask(__name__)

# ============ 常量 ============

MAX_HOPS = 5
MAX_CHAIN_LENGTH = 5
PENDING_TIMEOUT_SEC = 600
DLQ_TAG = "dead_letter"
CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")

_pheromone_lock = threading.Lock()

# ============ Agent 模型 ============

class AgentProfile:
    def __init__(self, agent_id, name, role, specialty="", peer_eps=None, judgment_criteria=None):
        self.agent_id = agent_id
        self.name = name
        self.role = role
        self.specialty = specialty
        self.peer_eps = peer_eps or []
        self.judgment_criteria = judgment_criteria or []

    def to_dict(self):
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "role": self.role,
            "specialty": self.specialty,
            "peer_eps": self.peer_eps,
            "judgment_criteria": self.judgment_criteria
        }

# ============ 加载配置 ============

def load_agents():
    """从 config/agents.json 加载 agent 列表，不存在则返回默认3个"""
    path = os.path.join(CONFIG_DIR, "agents.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return [AgentProfile(**a) for a in data]
    # 默认示例 agent
    return [
        AgentProfile("agent_001", "Agent Alpha", "worker"),
        AgentProfile("agent_002", "Agent Beta", "coordinator"),
        AgentProfile("agent_003", "Agent Gamma", "approver"),
    ]

def load_hooks():
    """从 config/hooks.json 加载 hook 规则"""
    path = os.path.join(CONFIG_DIR, "hooks.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"on_create": {}}

AGENTS = load_agents()
HOOKS = load_hooks()

# ============ Pheromone 模型 ============

class Pheromone:
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_TIMEOUT = "timeout"

    def __init__(self, type, sender, targets=None, content="",
                 parent_pheromone_id=None, judgment_status="pending",
                 metadata=None, hop_count=0):
        self.id = str(uuid.uuid4())[:8]
        self.type = type
        self.sender = sender
        self.targets = targets or []
        self.content = content
        self.parent_pheromone_id = parent_pheromone_id
        self.judgment_status = judgment_status
        self.metadata = metadata or {}
        self.timestamp = datetime.utcnow().isoformat() + "Z"
        self.hop_count = hop_count
        self.status = judgment_status
        self._created_at = datetime.utcnow()

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "sender": self.sender,
            "targets": self.targets,
            "content": self.content,
            "parent_pheromone_id": self.parent_pheromone_id,
            "judgment_status": self.judgment_status,
            "status": self.status,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "hop_count": self.hop_count,
            "exceeded": self.hop_count >= MAX_HOPS
        }

    def get_age_seconds(self):
        return (datetime.utcnow() - self._created_at).total_seconds()

    def should_escalate(self):
        return self.hop_count >= MAX_HOPS

# ============ 存储 ============

pheromones = []
dlq = []

# ============ 工具函数 ============

def compute_hop_count(parent_id):
    if not parent_id:
        return 0
    for p in pheromones:
        if p.id == parent_id:
            return p.hop_count + 1
    return 0

def check_dlq():
    """检查超时 pheromone，移入 DLQ（需锁保护）"""
    global dlq
    with _pheromone_lock:
        for p in pheromones:
            if p.status == Pheromone.STATUS_PENDING and p.get_age_seconds() > PENDING_TIMEOUT_SEC:
                p.status = Pheromone.STATUS_TIMEOUT
                p.metadata[DLQ_TAG] = True
                p.metadata["timeout_at"] = datetime.utcnow().isoformat() + "Z"
                if p not in dlq:
                    dlq.append(p)
    return dlq

def cleanup_ttl():
    """清理 TTL 过期的 pheromone"""
    now = datetime.utcnow()
    global pheromones
    with _pheromone_lock:
        original_len = len(pheromones)
        pheromones = [p for p in pheromones if not is_expired(p)]
        removed = original_len - len(pheromones)
    return removed

def is_expired(p):
    """检查 pheromone 是否已过期（TTL 或 explicit expiration）"""
    if p.status in (Pheromone.STATUS_APPROVED, Pheromone.STATUS_REJECTED, Pheromone.STATUS_TIMEOUT):
        return False
    ttl = p.metadata.get("ttl_seconds")
    if ttl:
        return p.get_age_seconds() > ttl
    return False

def trigger_hooks(p):
    """根据 hooks.json 配置，在 pheromone 创建后触发"""
    rules = HOOKS.get("on_create", {})
    rule = rules.get(p.type)
    if not rule:
        return
    action = rule.get("action")
    if action == "reply":
        reply = Pheromone(
            type=rule.get("reply_type", "auto_reply"),
            sender=rule.get("sender"),
            targets=rule.get("targets", []),
            content=rule.get("content", ""),
            parent_pheromone_id=p.id,
            metadata={"triggered_by": p.id},
            hop_count=p.hop_count + 1
        )
        with _pheromone_lock:
            pheromones.append(reply)

def validated_sender(data):
    sender = request.headers.get("X-Agent-ID")
    if not sender:
        sender = data.get("sender")
    return sender

# ============ API ============

@app.route("/api/agents", methods=["GET"])
def get_agents():
    return jsonify({a.agent_id: a.to_dict() for a in AGENTS})

@app.route("/api/agents", methods=["POST"])
def create_agent():
    """注册新 agent"""
    data = request.json or {}
    agent_id = data.get("agent_id")
    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400
    if any(a.agent_id == agent_id for a in AGENTS):
        return jsonify({"error": "agent_id already exists"}), 409
    agent = AgentProfile(
        agent_id=agent_id,
        name=data.get("name", agent_id),
        role=data.get("role", "unknown"),
        specialty=data.get("specialty", ""),
        peer_eps=data.get("peer_eps", []),
        judgment_criteria=data.get("judgment_criteria", [])
    )
    AGENTS.append(agent)
    return jsonify(agent.to_dict()), 201

@app.route("/api/agents/<agent_id>", methods=["DELETE"])
def delete_agent(agent_id):
    global AGENTS
    AGENTS = [a for a in AGENTS if a.agent_id != agent_id]
    return jsonify({"status": "deleted"})

@app.route("/api/agents/<agent_id>", methods=["PUT"])
def update_agent(agent_id):
    data = request.json or {}
    for a in AGENTS:
        if a.agent_id == agent_id:
            a.name = data.get("name", a.name)
            a.role = data.get("role", a.role)
            a.specialty = data.get("specialty", a.specialty)
            a.peer_eps = data.get("peer_eps", a.peer_eps)
            a.judgment_criteria = data.get("judgment_criteria", a.judgment_criteria)
            return jsonify(a.to_dict())
    return jsonify({"error": "not found"}), 404

@app.route("/api/pheromones", methods=["GET"])
def get_pheromones():
    check_dlq()
    cleanup_ttl()
    return jsonify([p.to_dict() for p in pheromones])

@app.route("/api/pheromones", methods=["POST"])
def create_pheromone():
    data = request.json or {}
    sender = validated_sender(data)
    if not sender:
        return jsonify({"error": "sender required (X-Agent-ID header or sender field)"}), 400

    parent_id = data.get("parent_pheromone_id")
    hop_count = compute_hop_count(parent_id)

    # 创建 pheromone（不含 hop_count，让 compute_hop_count 算）
    p = Pheromone(
        type=data.get("type", "message"),
        sender=sender,
        targets=data.get("targets", []),
        content=data.get("content", ""),
        parent_pheromone_id=parent_id,
        metadata=data.get("metadata", {}),
        hop_count=hop_count
    )

    with _pheromone_lock:
        pheromones.append(p)

        if p.should_escalate():
            p.metadata["escalated"] = True
            p.metadata["human_intervention"] = True
            p.status = Pheromone.STATUS_TIMEOUT

    # 锁外调用 trigger（防止死锁）
    trigger_hooks(p)

    return jsonify(p.to_dict()), 201

@app.route("/api/pheromones/<pid>", methods=["GET"])
def get_pheromone(pid):
    for p in pheromones:
        if p.id == pid:
            return jsonify(p.to_dict())
    return jsonify({"error": "not found"}), 404

@app.route("/api/pheromones/<pid>/judge", methods=["PUT"])
def judge_pheromone(pid):
    """审批 pheromone（approve/reject）"""
    data = request.json or {}
    judgment = data.get("judgment_status")
    if judgment not in ("approved", "rejected"):
        return jsonify({"error": "judgment_status must be approved or rejected"}), 400

    with _pheromone_lock:
        for p in pheromones:
            if p.id == pid:
                p.judgment_status = judgment
                p.status = judgment
                return jsonify(p.to_dict())

    return jsonify({"error": "not found"}), 404

@app.route("/api/chain/<pid>/tree", methods=["GET"])
def get_chain_tree(pid):
    """获取链路树形结构（分支可视化）"""
    visited = set()

    def build_tree(p_id):
        if p_id in visited:
            return None
        visited.add(p_id)
        p = next((x for x in pheromones if x.id == p_id), None)
        if not p:
            return None
        node = p.to_dict()
        children = []
        for child in pheromones:
            if child.parent_pheromone_id == p_id and child.id not in visited:
                child_node = build_tree(child.id)
                if child_node:
                    children.append(child_node)
        node["children"] = children
        return node

    root = build_tree(pid)
    if not root:
        return jsonify({"error": "pheromone not found"}), 404
    return jsonify(root)

@app.route("/api/chain/<pid>", methods=["GET"])
def get_chain(pid):
    chain = []
    target_id = pid
    visited = set()

    while target_id and target_id not in visited:
        visited.add(target_id)
        found = next((p for p in pheromones if p.id == target_id), None)
        if found:
            chain.append(found.to_dict())
            target_id = found.parent_pheromone_id if found.parent_pheromone_id != found.id else None
        else:
            break

    # 添加子链路
    for p in pheromones:
        if p.parent_pheromone_id == pid:
            chain.append(p.to_dict())
            chain.extend(get_sub_chain(p.id))

    return jsonify(chain)

def get_sub_chain(pid, visited=None):
    if visited is None:
        visited = set()
    if pid in visited:
        return []
    visited.add(pid)
    sub = []
    for p in pheromones:
        if p.parent_pheromone_id == pid and p.id not in visited:
            sub.append(p.to_dict())
            sub.extend(get_sub_chain(p.id, visited))
    return sub

@app.route("/api/dlq", methods=["GET"])
def get_dlq():
    check_dlq()
    return jsonify([p.to_dict() for p in dlq])

@app.route("/api/reset", methods=["POST"])
def reset():
    global pheromones, dlq
    pheromones = []
    dlq = []
    return jsonify({"status": "reset"})

@app.route("/api/hooks", methods=["GET"])
def get_hooks():
    """获取当前 hook 配置"""
    return jsonify(HOOKS)

@app.route("/api/hooks", methods=["PUT"])
def update_hooks():
    """更新 hook 配置"""
    global HOOKS
    data = request.json or {}
    HOOKS = data
    # 写回文件
    path = os.path.join(CONFIG_DIR, "hooks.json")
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(HOOKS, f, indent=2, ensure_ascii=False)
    return jsonify({"status": "updated", "hooks": HOOKS})

# ============ 前端 ============

@app.route("/")
def index():
    return """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Crew Demo - Pheromone Framework</title>
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
        .container { max-width: 1000px; margin: 0 auto; }

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

        .tab-nav {
            display: flex;
            gap: 4px;
            margin-bottom: 24px;
            border-bottom: 1px solid #222;
        }
        .tab-btn {
            background: transparent;
            color: #666;
            border: none;
            border-bottom: 2px solid transparent;
            padding: 10px 20px;
            font-size: 14px;
            cursor: pointer;
        }
        .tab-btn:hover { color: #aaa; }
        .tab-btn.active { color: #6366f1; border-bottom-color: #6366f1; }
        .scene { display: none; }
        .scene.active { display: block; }

        .agent-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 15px;
        }
        .agent-card {
            background: #16161e;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 15px;
        }
        .agent-card-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
        .agent-avatar {
            width: 36px; height: 36px;
            border-radius: 50%;
            background: #1a1a24;
            display: flex; align-items: center; justify-content: center;
            font-size: 16px;
        }
        .agent-info { flex: 1; }
        .agent-name { font-weight: 600; color: #fff; font-size: 14px; }
        .agent-role { font-size: 12px; color: #666; }
        .agent-id { font-size: 11px; color: #444; font-family: monospace; }
        .agent-tag {
            display: inline-block;
            background: #1a1a24;
            border: 1px solid #333;
            border-radius: 4px;
            padding: 3px 8px;
            font-size: 12px;
            color: #888;
            margin: 2px;
        }
        .agent-actions { margin-top: 10px; display: flex; gap: 8px; }

        .form-group { margin-bottom: 20px; }
        .form-group label { display: block; font-size: 13px; color: #888; margin-bottom: 8px; }
        input, textarea, select {
            width: 100%;
            background: #1a1a24;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 12px;
            color: #e0e0e0;
            font-size: 14px;
            font-family: inherit;
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
        }
        button:hover { background: #5558e3; }
        .btn-secondary {
            background: transparent;
            border: 1px solid #333;
            color: #888;
        }
        .btn-secondary:hover { border-color: #6366f1; color: #6366f1; }
        .btn-delete { background: #ef4444; }
        .btn-delete:hover { background: #dc2626; }

        .pheromone-list { margin-top: 20px; }
        .pheromone-item {
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
            min-width: 80px;
            text-align: center;
        }
        .pheromone-content { flex: 1; font-size: 14px; color: #aaa; }
        .pheromone-meta { font-size: 12px; color: #555; }
        .hop-badge {
            background: #333;
            color: #888;
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 3px;
        }

        .chain-visual {
            background: #16161e;
            border-radius: 8px;
            padding: 20px;
            margin-top: 15px;
        }
        .chain-node {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: #1a1a24;
            border: 1px solid #333;
            border-radius: 6px;
            padding: 8px 16px;
            margin: 4px;
            font-size: 13px;
        }
        .chain-arrow { color: #555; margin: 0 8px; }

        .empty-state { text-align: center; padding: 40px 20px; color: #444; }

        .add-agent-form {
            background: #1a1a24;
            border: 1px dashed #6366f1;
            border-radius: 8px;
            padding: 20px;
            margin-top: 20px;
        }

        .checkbox-group { display: flex; flex-wrap: wrap; gap: 10px; }
        .checkbox-item {
            display: flex;
            align-items: center;
            gap: 6px;
            background: #1a1a24;
            border: 1px solid #333;
            border-radius: 6px;
            padding: 6px 12px;
            font-size: 13px;
            cursor: pointer;
        }
        .checkbox-item input { width: auto; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Crew Demo <span style="font-size:14px;color:#666">v2.0</span></h1>
        <p class="subtitle">Generic Pheromone Framework · 零硬编码</p>

        <div class="tab-nav">
            <button class="tab-btn active" onclick="showTab('tab-agents')">Agents</button>
            <button class="tab-btn" onclick="showTab('tab-send')">Send Pheromone</button>
            <button class="tab-btn" onclick="showTab('tab-chain')">Chain Lookup</button>
            <button class="tab-btn" onclick="showTab('tab-hooks')">Hooks Config</button>
        </div>

        <!-- Tab: Agents -->
        <div id="tab-agents" class="scene active">
            <div class="card">
                <div class="card-title">Registered Agents</div>
                <div class="agent-grid" id="agent-grid">
                    <div class="empty-state">Loading...</div>
                </div>

                <div class="add-agent-form">
                    <div class="card-title" style="margin-bottom:12px;">Add New Agent</div>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                        <div class="form-group">
                            <label>Agent ID</label>
                            <input type="text" id="new-agent-id" placeholder="e.g. agent_004">
                        </div>
                        <div class="form-group">
                            <label>Name</label>
                            <input type="text" id="new-agent-name" placeholder="e.g. Agent Delta">
                        </div>
                        <div class="form-group">
                            <label>Role</label>
                            <input type="text" id="new-agent-role" placeholder="e.g. worker, coordinator, approver">
                        </div>
                        <div class="form-group">
                            <label>Specialty (optional)</label>
                            <input type="text" id="new-agent-specialty" placeholder="e.g. code review">
                        </div>
                    </div>
                    <button onclick="addAgent()" style="margin-top:8px;">Add Agent</button>
                </div>
            </div>
        </div>

        <!-- Tab: Send Pheromone -->
        <div id="tab-send" class="scene">
            <div class="card">
                <div class="card-title">Send Pheromone</div>
                <div class="form-group">
                    <label>Sender (from registered agents)</label>
                    <select id="send-sender"></select>
                </div>
                <div class="form-group">
                    <label>Type</label>
                    <input type="text" id="send-type" placeholder="e.g. message, task, approval">
                </div>
                <div class="form-group">
                    <label>Content</label>
                    <textarea id="send-content" rows="3" placeholder="Pheromone content..."></textarea>
                </div>
                <div class="form-group">
                    <label>Targets (multi-select)</label>
                    <div class="checkbox-group" id="send-targets"></div>
                </div>
                <div class="form-group">
                    <label>Parent Pheromone ID (optional, for chaining)</label>
                    <input type="text" id="send-parent" placeholder="Leave empty for root pheromone">
                </div>
                <button onclick="sendPheromone()">Send</button>
                <button class="btn-secondary" onclick="resetDemo()">Reset</button>
            </div>

            <div class="card">
                <div class="card-title">Pheromone List <span id="pheromone-count" style="color:#6366f1;">0</span></div>
                <div id="pheromone-list">
                    <div class="empty-state">No pheromones yet...</div>
                </div>
            </div>
        </div>

        <!-- Tab: Chain Lookup -->
        <div id="tab-chain" class="scene">
            <div class="card">
                <div class="card-title">Chain Visualization</div>
                <div class="form-group">
                    <label>Pheromone ID</label>
                    <input type="text" id="chain-pid" placeholder="Enter pheromone ID to visualize chain">
                </div>
                <button onclick="loadChain()">Lookup</button>

                <div id="chain-result" class="chain-visual">
                    <div class="empty-state">Enter a pheromone ID to view its chain</div>
                </div>
            </div>
        </div>

        <!-- Tab: Hooks Config -->
        <div id="tab-hooks" class="scene">
            <div class="card">
                <div class="card-title">Hook Rules</div>
                <p style="color:#666;font-size:13px;margin-bottom:20px;">
                    Hooks let you auto-trigger actions when a pheromone of a specific type is created.
                </p>
                <div id="hooks-list">
                    <div class="empty-state">No hooks configured</div>
                </div>

                <div class="add-agent-form">
                    <div class="card-title" style="margin-bottom:12px;">Add Hook Rule</div>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                        <div class="form-group">
                            <label>Trigger Type (pheromone type)</label>
                            <input type="text" id="hook-trigger-type" placeholder="e.g. task">
                        </div>
                        <div class="form-group">
                            <label>Auto Reply Sender</label>
                            <input type="text" id="hook-sender" placeholder="e.g. agent_002">
                        </div>
                        <div class="form-group">
                            <label>Reply Type</label>
                            <input type="text" id="hook-reply-type" placeholder="e.g. response">
                        </div>
                        <div class="form-group">
                            <label>Reply Targets (comma-separated)</label>
                            <input type="text" id="hook-targets" placeholder="e.g. agent_001, agent_003">
                        </div>
                    </div>
                    <div class="form-group">
                        <label>Reply Content</label>
                        <input type="text" id="hook-content" placeholder="Auto reply content...">
                    </div>
                    <button onclick="addHook()">Add Hook</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        async function loadAgents() {
            const agents = await fetch("/api/agents").then(r => r.json());
            const grid = document.getElementById("agent-grid");
            if (Object.keys(agents).length === 0) {
                grid.innerHTML = '<div class="empty-state">No agents registered. Add one below.</div>';
            } else {
                grid.innerHTML = Object.entries(agents).map(([id, a]) => `
                    <div class="agent-card">
                        <div class="agent-card-header">
                            <div class="agent-avatar">${a.name[0]}</div>
                            <div class="agent-info">
                                <div class="agent-name">${a.name}</div>
                                <div class="agent-role">${a.role}</div>
                                <div class="agent-id">${a.agent_id}</div>
                            </div>
                        </div>
                        ${a.specialty ? `<span class="agent-tag">${a.specialty}</span>` : ""}
                        ${(a.peer_eps || []).length ? `<div style="margin-top:8px;"><span class="agent-tag" style="border-color:#22c55e;color:#22c55e;">peers: ${a.peer_eps.join(", ")}</span></div>` : ""}
                        <div class="agent-actions">
                            <button class="btn-secondary btn-delete" onclick="deleteAgent('${a.agent_id}')" style="padding:6px 12px;font-size:12px;">Delete</button>
                        </div>
                    </div>
                `).join("");
            }

            // 更新 sender 下拉
            const senderSelect = document.getElementById("send-sender");
            senderSelect.innerHTML = Object.keys(agents).map(id => `<option value="${id}">${agents[id].name} (${id})</option>`).join("");

            // 更新 targets 多选
            const targetsDiv = document.getElementById("send-targets");
            targetsDiv.innerHTML = Object.entries(agents).map(([id, a]) => `
                <label class="checkbox-item">
                    <input type="checkbox" value="${id}" class="target-checkbox">
                    ${a.name}
                </label>
            `).join("");
        }

        async function addAgent() {
            const id = document.getElementById("new-agent-id").value.trim();
            const name = document.getElementById("new-agent-name").value.trim();
            const role = document.getElementById("new-agent-role").value.trim();
            const specialty = document.getElementById("new-agent-specialty").value.trim();
            if (!id || !name) { alert("agent_id and name required"); return; }
            await fetch("/api/agents", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ agent_id: id, name, role: role || "unknown", specialty })
            });
            ["new-agent-id","new-agent-name","new-agent-role","new-agent-specialty"].forEach(id => document.getElementById(id).value = "");
            await loadAgents();
        }

        async function deleteAgent(agentId) {
            if (!confirm("Delete agent " + agentId + "?")) return;
            await fetch("/api/agents/" + agentId, { method: "DELETE" });
            await loadAgents();
        }

        async function sendPheromone() {
            const sender = document.getElementById("send-sender").value;
            const type = document.getElementById("send-type").value.trim();
            const content = document.getElementById("send-content").value.trim();
            const parent = document.getElementById("send-parent").value.trim();
            const targets = Array.from(document.querySelectorAll(".target-checkbox:checked")).map(cb => cb.value);

            if (!type) { alert("type required"); return; }
            if (!content) { alert("content required"); return; }

            await fetch("/api/pheromones", {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-Agent-ID": sender },
                body: JSON.stringify({ type, sender, targets, content, parent_pheromone_id: parent || undefined })
            });
            await loadPheromones();
        }

        async function loadPheromones() {
            const ps = await fetch("/api/pheromones").then(r => r.json());
            document.getElementById("pheromone-count").textContent = ps.length;
            const list = document.getElementById("pheromone-list");
            if (ps.length === 0) {
                list.innerHTML = '<div class="empty-state">No pheromones yet...</div>';
            } else {
                list.innerHTML = ps.map(p => {
                    const statusBadge = p.status === 'pending' ? '<span style="background:#fbbf24;color:#000;padding:2px 6px;border-radius:3px;font-size:11px;">pending</span>' :
                                         p.status === 'approved' ? '<span style="background:#22c55e;color:#000;padding:2px 6px;border-radius:3px;font-size:11px;">approved</span>' :
                                         p.status === 'rejected' ? '<span style="background:#ef4444;color:#fff;padding:2px 6px;border-radius:3px;font-size:11px;">rejected</span>' :
                                         '<span style="background:#666;color:#fff;padding:2px 6px;border-radius:3px;font-size:11px;">' + p.status + '</span>';
                    const actionBtns = p.status === 'pending' ? `
                        <button onclick="judgePheromone('${p.id}', 'approved')" style="background:#22c55e;color:#000;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:12px;margin-left:8px;">✓</button>
                        <button onclick="judgePheromone('${p.id}', 'rejected')" style="background:#ef4444;color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:12px;margin-left:4px;">✗</button>
                    ` : '';
                    return `
                    <div class="pheromone-item">
                        <div class="pheromone-badge">${p.type}</div>
                        <div class="pheromone-content">${p.content.substring(0, 60)}${p.content.length > 60 ? '...' : ''}</div>
                        <div class="pheromone-meta">
                            <span>${p.sender}</span>
                            ${p.parent_pheromone_id ? ` → <span>${p.parent_pheromone_id}</span>` : ""}
                            <span class="hop-badge">hop ${p.hop_count}</span>
                            ${statusBadge}
                            ${actionBtns}
                        </div>
                    </div>
                `}).join("");
            }
        }

        async function judgePheromone(pid, judgment) {
            await fetch("/api/pheromones/" + pid + "/judge", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ judgment_status: judgment })
            });
            await loadPheromones();
        }

        async function loadChain() {
            const pid = document.getElementById("chain-pid").value.trim();
            if (!pid) { alert("Enter pheromone ID"); return; }

            // 先尝试树形结构
            const treeResp = await fetch("/api/chain/" + pid + "/tree");
            if (treeResp.ok) {
                const tree = await treeResp.json();
                renderChainTree(tree, pid);
                return;
            }

            // 降级到线性
            const chain = await fetch("/api/chain/" + pid).then(r => r.json());
            const result = document.getElementById("chain-result");
            if (chain.length === 0) {
                result.innerHTML = '<div class="empty-state">Chain not found</div>';
            } else {
                result.innerHTML = chain.map((p, i) => `
                    ${i > 0 ? '<span class="chain-arrow">→</span>' : ''}
                    <div class="chain-node">
                        <span class="pheromone-badge">${p.type}</span>
                        <span>${p.sender}</span>
                        <span style="color:#555;">${p.content.substring(0,30)}${p.content.length > 30 ? "..." : ""}</span>
                        <span class="hop-badge">${p.hop_count}</span>
                    </div>
                `).join("");
            }
        }

        function renderChainTree(node, rootId, depth = 0) {
            const result = document.getElementById("chain-result");
            const indent = depth * 20;

            // 构建当前节点
            let html = `<div style="margin-left:${indent}px;padding:4px 0;border-left:1px solid #333;">`;
            html += `<div class="chain-node" style="display:inline-flex;gap:8px;margin:2px 0;">
                <span class="pheromone-badge">${node.type}</span>
                <span>${node.sender || 'unknown'}</span>
                <span style="color:#555;font-size:12px;">${(node.content || '').substring(0,40)}${(node.content || '').length > 40 ? '...' : ''}</span>
                <span class="hop-badge">${node.hop_count}</span>
                ${node.status ? '<span style="font-size:11px;color:#888;">' + node.status + '</span>' : ''}
            </div>`;

            // 递归渲染子节点
            if (node.children && node.children.length > 0) {
                html += '<div style="margin-left:' + (indent + 10) + 'px;">';
                for (const child of node.children) {
                    html += renderChainTree(child, node.id, depth + 1);
                }
                html += '</div>';
            }

            html += '</div>';
            result.innerHTML = html;
        }

        async function loadHooks() {
            const hooks = await fetch("/api/hooks").then(r => r.json());
            const rules = hooks.on_create || {};
            const list = document.getElementById("hooks-list");
            const entries = Object.entries(rules);
            if (entries.length === 0) {
                list.innerHTML = '<div class="empty-state">No hooks configured</div>';
            } else {
                list.innerHTML = entries.map(([type, rule]) => `
                    <div style="background:#16161e;border:1px solid #333;border-radius:8px;padding:16px;margin-bottom:10px;">
                        <div style="margin-bottom:8px;">
                            <span class="pheromone-badge">${type}</span>
                            <span style="color:#888;font-size:13px;"> → auto ${rule.action}</span>
                        </div>
                        <div style="font-size:13px;color:#aaa;">sender: ${rule.sender} | reply_type: ${rule.reply_type} | targets: ${(rule.targets || []).join(", ")}</div>
                        <div style="font-size:13px;color:#666;margin-top:4px;">${rule.content || ""}</div>
                    </div>
                `).join("");
            }
        }

        async function addHook() {
            const trigger = document.getElementById("hook-trigger-type").value.trim();
            const sender = document.getElementById("hook-sender").value.trim();
            const replyType = document.getElementById("hook-reply-type").value.trim();
            const targets = document.getElementById("hook-targets").value.split(",").map(s => s.trim()).filter(Boolean);
            const content = document.getElementById("hook-content").value.trim();

            if (!trigger || !sender) { alert("trigger type and sender required"); return; }

            const hooks = await fetch("/api/hooks").then(r => r.json());
            hooks.on_create = hooks.on_create || {};
            hooks.on_create[trigger] = {
                action: "reply",
                sender,
                reply_type: replyType || "auto_reply",
                targets,
                content
            };
            await fetch("/api/hooks", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(hooks)
            });
            ["hook-trigger-type","hook-sender","hook-reply-type","hook-targets","hook-content"].forEach(id => document.getElementById(id).value = "");
            await loadHooks();
        }

        async function resetDemo() {
            await fetch("/api/reset", { method: "POST" });
            await loadPheromones();
        }

        function showTab(name) {
            document.querySelectorAll(".scene").forEach(s => s.classList.remove("active"));
            document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
            document.getElementById(name).classList.add("active");
            event.target.classList.add("active");
        }

        // Init
        loadAgents();
        loadPheromones();
        loadHooks();
    </script>
</body>
</html>
"""