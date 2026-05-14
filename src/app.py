"""
Crew Demo - 周报聚合场景
最小可演示版本 v1.3 双场景版

场景一：层级汇报（员工→Boss→老板/HR）
场景二：单人调度（一人发起点，多 Agent 并行处理，结果汇总）

安全协议（Hotfix）：
1. Hop Count Limit：防止 Pheromone Storm
2. 状态机 + DLQ：防止僵尸信息素
3. 记忆压缩：防止上下文雪崩
4. 身份强制验证：防止零信任违规
5. 强类型校验：防止薛定谔 JSON
6. 原子操作锁：防止并发双花

run: python src/app.py
"""
from flask import Flask, jsonify, request
from datetime import datetime
from enum import Enum
import uuid
import threading
import time

app = Flask(__name__)

# ============ 常量 ============

MAX_HOPS = 5           # 最大跳转次数
MAX_CHAIN_LENGTH = 5   # 链路长度阈值（触发记忆压缩）
PENDING_TIMEOUT_SEC = 600  # 10分钟超时
DLQ_TAG = "dead_letter"     # 死信队列标签

# ============ 漏洞五 Hotfix：并发锁 ============
# 保护 pheromone 读写操作的原子性
_pheromone_lock = threading.Lock()

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
        agent_id="employee_zeng", name="增", ep="EP001", role="员工",
        specialty="用户研究、产品设计",
        judgment_criteria=["需求是否真实", "用户是否需要"],
        peer_eps=["EP002", "EP003"]
    ),
    "boss_agent": AgentProfile(
        agent_id="boss_agent", name="Boss Agent", ep="EP002", role="AI Agent",
        specialty="团队协调、资源调配",
        judgment_criteria=["是否符合团队目标", "优先级是否合理", "资源是否够用"],
        peer_eps=["EP001", "EP003", "EP004"]
    ),
    "manager_peng": AgentProfile(
        agent_id="manager_peng", name="彭老板", ep="EP003", role="老板",
        specialty="战略决策、团队管理",
        judgment_criteria=["是否对公司有利", "风险是否可控", "ROI 是否合理"],
        peer_eps=["EP002"]
    ),
    "hr_li": AgentProfile(
        agent_id="hr_li", name="李HR", ep="EP004", role="HR",
        specialty="人力资源、政策合规",
        judgment_criteria=["是否合规", "是否公平", "是否可持续"],
        peer_eps=["EP002", "EP003"]
    ),
    # 场景二：单人调度多 Agent
    "xiaomei": AgentProfile(
        agent_id="xiaomei", name="浩", ep="EP005", role="AI Agent",
        specialty="技术架构、代码评审",
        judgment_criteria=["技术可行性", "代码质量", "性能影响"],
        peer_eps=["EP001", "EP002", "EP004"]
    ),
}

# ============ 身份验证（漏洞三 Hotfix） ============
# sender 必须从请求头 X-Agent-ID 读取，禁止客户端伪造

def validated_sender(request_data):
    """
    漏洞三 Hotfix：强制从请求头读取 sender，禁止客户端伪造。
    Demo 环境使用简单模拟（生产环境应使用 JWT/Session）。
    """
    # 优先从 header 读取（模拟可信来源）
    sender = request.headers.get("X-Agent-ID")
    if not sender:
        sender = request_data.get("sender")
    return sender

# ============ 数据模型 ============

class Pheromone:
    # 状态机（漏洞二 Hotfix：补全状态）
    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_TIMEOUT = "timeout"  # 新增
    STATUS_FAILED = "failed"    # 新增

    def __init__(self, id=None, type=None, sender=None, targets=None, content=None,
                 parent_pheromone_id=None, judgment_status="pending", metadata=None,
                 hop_count=0):
        self.id = id or str(uuid.uuid4())[:8]
        self.type = type
        self.sender = sender  # 由 validated_sender() 强制写入
        self.targets = targets or []
        self.content = content
        self.parent_pheromone_id = parent_pheromone_id
        self.judgment_status = judgment_status
        self.metadata = metadata or {}
        self.timestamp = datetime.utcnow().isoformat() + "Z"
        self.hop_count = hop_count
        self.status = judgment_status  # 兼容旧字段
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

    def should_escalate(self):
        """检查 hop_count 是否超过限制"""
        return self.hop_count >= MAX_HOPS

    def get_age_seconds(self):
        """获取信息素存活时长（秒）"""
        return (datetime.utcnow() - self._created_at).total_seconds()

# ============ 漏洞四 Hotfix：Schema 校验（防止薛定谔 JSON） ============
# 不信任 LLM 输出的纯文本，必须校验后使用
class TaskType(str, Enum):
    TASK = "task"
    ISSUE = "issue"

class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class PheromoneType(str, Enum):
    WEEKLY_REPORT = "weekly_report"
    WEEKLY_DIGEST = "weekly_digest"
    APPROVAL = "approval"
    TASK = "task"
    ISSUE = "issue"
    SUMMARY = "summary"
    # 场景二：单人调度多 Agent
    TASK_DISPATCH = "task_dispatch"      # 任务分发（增→Boss）
    TECH_REVIEW = "tech_review"          # 技术评审（Boss→浩）
    RESOURCE_CONFIRM = "resource_confirm" # 资源确认（Boss→HR）
    FINAL_REPORT = "final_report"        # 最终汇总（Boss→增）

def validate_task_payload(data):
    """
    漏洞四 Hotfix：强类型校验，拒绝非结构化 JSON。
    LLM 输出可能包含 markdown 包装、尾逗花、大小写错误。
    返回 (is_valid, error_message)
    """
    errors = []

    # task_type 校验
    task_type = data.get("task_type", "")
    try:
        TaskType(task_type)
    except ValueError:
        valid_types = [t.value for t in TaskType]
        errors.append(f'task_type 必须是 {valid_types} 之一，实际收到: {task_type}')

    # priority 校验
    priority = data.get("priority", "")
    if priority:  # priority 可选
        try:
            Priority(priority.lower())
        except ValueError:
            valid_priorities = [p.value for p in Priority]
            errors.append(f'priority 必须是 {valid_priorities} 之一，实际收到: {priority}')

    # content 校验（必须有）
    content = data.get("content", "").strip()
    if not content:
        errors.append('content 不能为空')

    if errors:
        return False, "; ".join(errors)
    return True, ""

# ============ 存储 ============

pheromones = []
dlq = []  # 死信队列

# ============ 工具函数 ============

def compute_hop_count(parent_id):
    """计算新 pheromone 的 hop_count（基于 parent）"""
    if not parent_id:
        return 0
    for p in pheromones:
        if p.id == parent_id:
            return p.hop_count + 1
    return 0

def check_dlq():
    """
    漏洞二 Hotfix：死信队列扫描
    每当有 pending 状态超过 PENDING_TIMEOUT_SEC 的信息素，打入 DLQ
    """
    global dlq
    now_pending = [p for p in pheromones if p.status == Pheromone.STATUS_PENDING]
    for p in now_pending:
        if p.get_age_seconds() > PENDING_TIMEOUT_SEC:
            p.status = Pheromone.STATUS_TIMEOUT
            p.metadata[DLQ_TAG] = True
            p.metadata["timeout_at"] = datetime.utcnow().isoformat() + "Z"
            dlq.append(p)
    return dlq

def compress_chain(report_id):
    """
    漏洞三 Hotfix：记忆压缩
    当链路长度超过 MAX_CHAIN_LENGTH 时，生成压缩摘要
    """
    chain = get_chain_data(report_id)
    if len(chain) <= MAX_CHAIN_LENGTH:
        return None

    # 压缩：保留头部（原始请求）+ 尾部（最近2条）+ 中间压缩
    summary_content = []
    for i, p in enumerate(chain):
        if i == 0:
            summary_content.append(f"原始：{p['content'][:50]}...")
        elif i >= len(chain) - 2:
            summary_content.append(f"{p['type']}：{p['content'][:30]}...")
        elif p['type'] == 'summary':
            summary_content.append(f"摘要：{p['content'][:50]}...")

    return {
        "type": "summary",
        "content": " | ".join(summary_content),
        "compressed_from": len(chain)
    }

def get_chain_data(pid):
    """获取链路数据（不调用 API，纯内部函数）"""
    chain = []
    target_id = pid
    visited = set()

    while target_id and target_id not in visited:
        visited.add(target_id)
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

    return chain

# ============ API ============

@app.route("/api/participants", methods=["GET"])
def get_participants():
    return jsonify({k: {"name": v.name, "ep": v.ep, "role": v.role} for k, v in AGENT_PROFILES.items()})

@app.route("/api/agents/profiles", methods=["GET"])
def get_agent_profiles():
    return jsonify({k: v.to_dict() for k, v in AGENT_PROFILES.items()})

@app.route("/api/agents/<agent_id>/create_task", methods=["POST"])
def agent_create_task(agent_id):
    """Agent 主动创建 Task（漏洞五：加锁 + 漏洞四：Schema 校验）"""
    if agent_id not in AGENT_PROFILES:
        return jsonify({"error": "agent not found"}), 404

    data = request.json or {}

    # 漏洞四：强类型校验
    is_valid, err_msg = validate_task_payload(data)
    if not is_valid:
        return jsonify({
            "error": "schema_validation_failed",
            "detail": err_msg,
            "hint": "task_type 必须是 task/issue，priority 必须是 low/medium/high，content 必须非空"
        }), 400

    # 漏洞五：并发锁
    with _pheromone_lock:
        p = Pheromone(
            type=data.get("task_type"),
            sender=validated_sender(data) or agent_id,
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
    check_dlq()  # 每次查询前扫描 DLQ
    return jsonify([p.to_dict() for p in pheromones])

@app.route("/api/pheromones", methods=["POST"])
def create_pheromone():
    data = request.json

    # 漏洞三：sender 强制验证，禁止伪造
    sender = validated_sender(data)

    # 漏洞五：并发锁保护
    with _pheromone_lock:
        # 计算 hop_count
        parent_id = data.get("parent_pheromone_id")
        hop_count = compute_hop_count(parent_id)

        p = Pheromone(
            type=data.get("type"),
            sender=sender,
            targets=data.get("targets", []),
            content=data.get("content"),
            parent_pheromone_id=parent_id,
            metadata=data.get("metadata", {}),
            hop_count=hop_count
        )
        pheromones.append(p)

        # 漏洞一：hop_count 超过限制 → escalate
        if p.should_escalate():
            p.metadata["escalated"] = True
            p.metadata["human_intervention"] = True
            p.status = Pheromone.STATUS_FAILED
            return jsonify({
                "status": "escalated",
                "pheromone": p.to_dict(),
                "warning": f"链路跳数超过 {MAX_HOPS}，已转交人类处理"
            }), 201

        # 漏洞二：处理超时检测
        check_dlq()

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

@app.route("/api/dlq", methods=["GET"])
def get_dlq():
    """获取死信队列"""
    check_dlq()
    return jsonify([p.to_dict() for p in dlq])

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
    global pheromones, dlq
    pheromones = []
    dlq = []
    return jsonify({"status": "reset"})

# ============ 业务逻辑 ============

def handle_weekly_report(p):
    boss_profile = AGENT_PROFILES.get("boss_agent")

    digest = Pheromone(
        type="weekly_digest",
        sender="boss_agent",  # 固定为 Boss Agent，不接受客户端传入
        targets=["manager_peng", "hr_li"],
        content=generate_digest_content(),
        parent_pheromone_id=p.id,
        metadata={
            "source_report_id": p.id,
            "judging_agent": "boss_agent",
            "judgment_criteria": boss_profile.judgment_criteria if boss_profile else []
        },
        hop_count=p.hop_count + 1
    )
    pheromones.append(digest)

    if digest.should_escalate():
        digest.metadata["escalated"] = True
        digest.metadata["human_intervention"] = True

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
                parent.status = p.judgment_status
                break

# ============ 场景二：单人调度多 Agent ============

@app.route("/api/multi/dispatch", methods=["POST"])
def multi_dispatch():
    """
    场景二：增发起任务，Boss Agent 分解分发到浩（技术）和 HR（资源）
    并行处理后 Boss Agent 汇总结果给增
    """
    data = request.json or {}
    sender = validated_sender(data)

    with _pheromone_lock:
        # 1. 增发起任务分发
        dispatch = Pheromone(
            type="task_dispatch",
            sender=sender,
            targets=["boss_agent"],
            content=data.get("content", "新功能开发任务"),
            metadata={
                "original_sender": sender,
                "task_name": data.get("task_name", "未命名任务")
            },
            hop_count=0
        )
        pheromones.append(dispatch)

        # 2. Boss Agent 自动分发给浩（技术评审）和 HR（资源确认）
        tech_review = Pheromone(
            type="tech_review",
            sender="boss_agent",
            targets=["xiaomei"],
            content=f"技术评审请求：{dispatch.content}",
            parent_pheromone_id=dispatch.id,
            metadata={
                "parent_dispatch_id": dispatch.id,
                "reviewer": "xiaomei",
                "aspect": "技术可行性 + 代码质量 + 性能影响"
            },
            hop_count=1
        )
        pheromones.append(tech_review)

        resource_confirm = Pheromone(
            type="resource_confirm",
            sender="boss_agent",
            targets=["hr_li"],
            content=f"资源确认请求：{dispatch.content}",
            parent_pheromone_id=dispatch.id,
            metadata={
                "parent_dispatch_id": dispatch.id,
                "reviewer": "hr_li",
                "aspect": "人力资源 + 政策合规"
            },
            hop_count=1
        )
        pheromones.append(resource_confirm)

        return jsonify({
            "dispatch": dispatch.to_dict(),
            "branches": [tech_review.to_dict(), resource_confirm.to_dict()]
        }), 201

@app.route("/api/multi/respond", methods=["POST"])
def multi_respond():
    """
    场景二：浩（技术评审）或 HR（资源确认）响应
    两者都 approved 后，Boss Agent 自动生成 final_report 汇总给增
    """
    data = request.json or {}
    sender = validated_sender(data)
    parent_id = data.get("parent_pheromone_id")
    judgment = data.get("judgment_status", "approved")  # approved / rejected
    content = data.get("content", "")

    with _pheromone_lock:
        # 找到父 pheromone
        parent = None
        for p in pheromones:
            if p.id == parent_id:
                parent = p
                break

        if not parent:
            return jsonify({"error": "parent not found"}), 404

        # 创建响应 pheromone
        response_type = parent.type  # tech_review 或 resource_confirm
        response = Pheromone(
            type=response_type,
            sender=sender,
            targets=[parent.metadata.get("original_sender", "employee_zeng")],
            content=content or f"{sender} 已完成 {response_type} 评审",
            parent_pheromone_id=parent_id,
            judgment_status=judgment,
            metadata={
                "response_to": parent_id,
                "reviewer": sender
            },
            hop_count=parent.hop_count + 1
        )
        pheromones.append(response)

        # 更新父 pheromone 状态
        parent.judgment_status = judgment
        parent.status = judgment

        # 检查是否两个都完成了
        dispatch_id = parent.metadata.get("parent_dispatch_id")
        if dispatch_id and judgment == "approved":
            # 查找同级的另一个 review
            sibling_type = "resource_confirm" if parent.type == "tech_review" else "tech_review"
            sibling_approved = False
            for p in pheromones:
                if p.metadata.get("parent_dispatch_id") == dispatch_id and p.type == sibling_type:
                    if p.judgment_status == "approved":
                        sibling_approved = True
                        break

            # 两者都 approved，生成 final_report
            if sibling_approved:
                # 查找原始 dispatch 的 sender
                dispatch_sender = "employee_zeng"
                for p in pheromones:
                    if p.id == dispatch_id:
                        dispatch_sender = p.metadata.get("original_sender", "employee_zeng")
                        break

                final_report = Pheromone(
                    type="final_report",
                    sender="boss_agent",
                    targets=[dispatch_sender],
                    content=f"任务已完成汇总：技术评审通过，资源确认通过。请知悉。",
                    parent_pheromone_id=dispatch_id,
                    metadata={
                        "summary": "技术+资源双评审通过，任务可执行",
                        "tech_reviewer": "xiaomei",
                        "resource_reviewer": "hr_li"
                    },
                    hop_count=2
                )
                pheromones.append(final_report)
                return jsonify({
                    "response": response.to_dict(),
                    "final_report": final_report.to_dict(),
                    "both_approved": True
                }), 201

        return jsonify({"response": response.to_dict(), "both_approved": False}), 201

@app.route("/api/multi/pending", methods=["GET"])
def multi_pending():
    """获取当前需要响应的 tech_review 和 resource_confirm"""
    pending = [p for p in pheromones if p.type in ("tech_review", "resource_confirm") and p.status == "pending"]
    return jsonify([p.to_dict() for p in pending])

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
        .pheromone-badge.summary { background: #f59e0b; }
        .pheromone-content { flex: 1; font-size: 14px; color: #aaa; }
        .pheromone-status { font-size: 12px; padding: 4px 10px; border-radius: 4px; }
        .pheromone-status.pending { background: #fbbf24; color: #000; }
        .pheromone-status.approved { background: #22c55e; color: #000; }
        .pheromone-status.timeout { background: #ef4444; color: #fff; }

        .hop-badge {
            background: #333;
            color: #888;
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 3px;
            margin-left: 8px;
        }
        .hop-badge.warning { background: #f59e0b; color: #000; }
        .hop-badge.danger { background: #ef4444; color: #fff; }

        .dlq-warning {
            background: #ef4444;
            color: #fff;
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 13px;
            margin-bottom: 15px;
        }

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
        .btn-agent { background: #8b5cf6; }
        .btn-agent:hover { background: #7c3aed; }

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

        .empty-state { text-align: center; padding: 40px 20px; color: #444; }

        /* Tab 切换 */
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
            transition: all 0.2s;
        }
        .tab-btn:hover { color: #aaa; }
        .tab-btn.active {
            color: #6366f1;
            border-bottom-color: #6366f1;
        }
        .scene { display: none; }
        .scene.active { display: block; }

        /* 场景二样式 */
        .dispatch-flow {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 15px;
            flex-wrap: wrap;
            padding: 20px;
            background: #16161e;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .dispatch-node {
            background: #1a1a24;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 12px 18px;
            text-align: center;
        }
        .dispatch-node .node-name { font-weight: 600; color: #fff; }
        .dispatch-node .node-role { font-size: 12px; color: #666; margin-top: 4px; }
        .branch-arrow {
            font-size: 20px;
            color: #555;
        }
        .pending-review {
            background: #1a1a24;
            border: 1px solid #8b5cf6;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 12px;
        }
        .pending-review .review-type {
            font-size: 12px;
            color: #8b5cf6;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 8px;
        }
        .pending-review .review-content {
            font-size: 14px;
            color: #ccc;
            margin-bottom: 12px;
        }
        .review-badges {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .review-badge {
            font-size: 11px;
            padding: 3px 8px;
            border-radius: 4px;
        }
        .review-badge.tech { background: #3b82f6; color: #fff; }
        .review-badge.resource { background: #f59e0b; color: #000; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Crew Demo <span style="font-size:14px;color:#666">v1.3</span></h1>
        <p class="subtitle">双场景版 · Pheromone 链演示</p>

        <div class="tab-nav">
            <button class="tab-btn active" onclick="showScene('scene1')">场景一：层级汇报</button>
            <button class="tab-btn" onclick="showScene('scene2')">场景二：单人调度多 Agent</button>
        </div>

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
            <div class="status-card">
                <div class="status-number" id="dlq-count">0</div>
                <div class="status-label">死信队列</div>
            </div>
        </div>

        <div id="dlq-alert" style="display:none;" class="dlq-warning">
            ⚠️ 有信息素超时进入死信队列，请检查！
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

        <!-- 场景一：层级汇报 -->
        <div id="scene1" class="scene active">
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
                <div class="card-title">Agent 主动创建 Task（Multica 启发）</div>
                <div class="task-section">
                    <div class="form-group">
                        <label>任务内容</label>
                        <input type="text" id="task-content" placeholder="Boss Agent 发现问题时主动创建">
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
        </div>

        <!-- 场景二：单人调度多 Agent -->
        <div id="scene2" class="scene">
            <div class="card">
                <div class="card-title">单人调度多 Agent 演示</div>
                <div class="dispatch-flow">
                    <div class="dispatch-node">
                        <div class="node-name">增</div>
                        <div class="node-role">发起任务</div>
                    </div>
                    <span class="branch-arrow">→</span>
                    <div class="dispatch-node" style="border-color:#6366f1;">
                        <div class="node-name">Boss Agent</div>
                        <div class="node-role">任务分解</div>
                    </div>
                    <span class="branch-arrow">↙↘</span>
                    <div class="dispatch-node">
                        <div class="node-name">浩</div>
                        <div class="node-role">技术评审</div>
                    </div>
                    <div class="dispatch-node">
                        <div class="node-name">HR</div>
                        <div class="node-role">资源确认</div>
                    </div>
                    <span class="branch-arrow">↘↙</span>
                    <div class="dispatch-node" style="border-color:#22c55e;">
                        <div class="node-name">增</div>
                        <div class="node-role">收总结果</div>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-title">发起任务分发</div>
                <div class="form-group">
                    <label>任务名称</label>
                    <input type="text" id="dispatch-task-name" placeholder="例如：开发新功能">
                </div>
                <div class="form-group">
                    <label>任务描述</label>
                    <textarea id="dispatch-content" placeholder="描述任务内容..."></textarea>
                </div>
                <button class="btn-agent" onclick="dispatchTask()">增发起任务分发</button>
            </div>

            <div class="card">
                <div class="card-title">待响应评审 <span id="pending-count" style="color:#8b5cf6;font-weight:600;">0</span></div>
                <div id="pending-reviews">
                    <div class="empty-state">暂无待处理评审...</div>
                </div>
            </div>

            <div class="card">
                <div class="card-title">最终报告</div>
                <div id="final-reports">
                    <div class="empty-state">等待 Boss Agent 汇总...</div>
                </div>
            </div>

            <div class="card">
                <div class="card-title">全链路追溯</div>
                <div id="dispatch-chain">
                    <div class="empty-state">暂无链路...</div>
                </div>
            </div>

            <div style="text-align:center;margin:20px 0;">
                <button class="btn-secondary" onclick="resetDemo()">重置</button>
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
                    headers: { "Content-Type": "application/json", "X-Agent-ID": "employee_zeng" },
                    body: JSON.stringify({ type: "weekly_report", sender: "employee_zeng", targets: ["boss_agent"], content })
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
                headers: { "Content-Type": "application/json", "X-Agent-ID": "boss_agent" },
                body: JSON.stringify({ content, task_type: document.getElementById("task-type").value, targets: ["manager_peng"] })
            });
            document.getElementById("task-content").value = "";
            await refresh();
        }

        async function approve(pid) {
            await fetch("/api/pheromones", {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-Agent-ID": "manager_peng" },
                body: JSON.stringify({ type: "approval", sender: "manager_peng", targets: [pid], content: "已阅", parent_pheromone_id: pid, judgment_status: "approved" })
            });
            await refresh();
        }

        async function refresh() {
            const [pheromones, dlq] = await Promise.all([
                fetch("/api/pheromones").then(r => r.json()),
                fetch("/api/dlq").then(r => r.json())
            ]);

            document.getElementById("total-count").textContent = pheromones.length;
            document.getElementById("pending-count").textContent = pheromones.filter(p => p.status === "pending").length;
            document.getElementById("approved-count").textContent = pheromones.filter(p => p.status === "approved").length;
            document.getElementById("dlq-count").textContent = dlq.length;

            const alert = document.getElementById("dlq-alert");
            alert.style.display = dlq.length > 0 ? "block" : "none";

            const list = document.getElementById("pheromone-list");
            if (pheromones.length === 0) {
                list.innerHTML = '<div class="empty-state">暂无信息...</div>';
            } else {
                list.innerHTML = pheromones.map(p => {
                    const statusClass = p.status === "pending" ? "pending" : p.status === "timeout" ? "timeout" : "approved";
                    const statusText = p.status === "pending" ? "待审批" : p.status === "timeout" ? "超时" : "已审批";
                    let badgeClass = "pheromone-badge";
                    if (p.type === 'task') badgeClass += " task";
                    else if (p.type === 'issue') badgeClass += " issue";
                    else if (p.type === 'summary') badgeClass += " summary";

                    let hopClass = "hop-badge";
                    if (p.hop_count >= 4) hopClass += " danger";
                    else if (p.hop_count >= 3) hopClass += " warning";

                    return `
                        <div class="pheromone-line">
                            <div class="${badgeClass}">${p.type}</div>
                            <div class="pheromone-content">
                                ${p.content}
                                <span class="${hopClass}">hop ${p.hop_count}</span>
                            </div>
                            <div>
                                <span class="pheromone-status ${statusClass}">${statusText}</span>
                                ${p.status === "pending" && p.type === "weekly_digest" ? `
                                    <button onclick="approve('${p.id}')" style="margin-left:10px;padding:4px 12px;font-size:12px;background:#22c55e;color:#000;border:none;border-radius:4px;cursor:pointer">批准</button>
                                ` : ''}
                            </div>
                        </div>
                    `;
                }).join("");
            }
        }

        async function loadProfiles() {
            const data = await fetch("/api/agents/profiles").then(r => r.json());
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
            await fetch("/api/reset", { method: "POST" });
            await refresh();
            await loadPendingReviews();
        }

        // 场景切换
        function showScene(name) {
            document.querySelectorAll('.scene').forEach(s => s.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.getElementById(name).classList.add('active');
            event.target.classList.add('active');
        }

        // 场景二：任务分发
        async function dispatchTask() {
            const taskName = document.getElementById("dispatch-task-name").value.trim();
            const content = document.getElementById("dispatch-content").value.trim();
            if (!content) { alert("请填写任务描述"); return; }
            await fetch("/api/multi/dispatch", {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-Agent-ID": "employee_zeng" },
                body: JSON.stringify({ task_name: taskName, content })
            });
            document.getElementById("dispatch-task-name").value = "";
            document.getElementById("dispatch-content").value = "";
            await loadPendingReviews();
            await refresh();
        }

        // 场景二：加载待评审
        async function loadPendingReviews() {
            const pending = await fetch("/api/multi/pending").then(r => r.json());
            document.getElementById("pending-count").textContent = pending.length;
            const container = document.getElementById("pending-reviews");
            if (pending.length === 0) {
                container.innerHTML = '<div class="empty-state">暂无待处理评审...</div>';
            } else {
                container.innerHTML = pending.map(p => {
                    const badgeClass = p.type === "tech_review" ? "tech" : "resource";
                    const reviewer = p.type === "tech_review" ? "浩" : "HR";
                    return `
                        <div class="pending-review">
                            <div class="review-type">${p.type === "tech_review" ? "技术评审" : "资源确认"}</div>
                            <div class="review-content">${p.content}</div>
                            <div class="review-badges">
                                <span class="review-badge ${badgeClass}">${reviewer} 评审</span>
                                <span style="font-size:12px;color:#666;">hop ${p.hop_count}</span>
                            </div>
                            <div style="margin-top:12px;display:flex;gap:10px;">
                                <button onclick="respondReview('${p.id}', 'approved', '${reviewer}')" style="background:#22c55e;color:#000;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:13px;">批准</button>
                                <button onclick="respondReview('${p.id}', 'rejected', '${reviewer}')" style="background:#ef4444;color:#fff;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:13px;">退回</button>
                            </div>
                        </div>
                    `;
                }).join("");
            }
            // 加载最终报告
            await loadFinalReports();
        }

        // 场景二：响应评审
        async function respondReview(pid, judgment, reviewerRole) {
            const sender = reviewerRole === "浩" ? "xiaomei" : "hr_li";
            const content = judgment === "approved"
                ? `${reviewerRole} 评审通过`
                : `${reviewerRole} 评审退回，建议修改`;
            const result = await fetch("/api/multi/respond", {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-Agent-ID": sender },
                body: JSON.stringify({ parent_pheromone_id: pid, judgment_status: judgment, content })
            }).then(r => r.json());
            await loadPendingReviews();
            await refresh();
            if (result.final_report) {
                await loadFinalReports();
            }
        }

        // 场景二：加载最终报告
        async function loadFinalReports() {
            const pheromones = await fetch("/api/pheromones").then(r => r.json());
            const reports = pheromones.filter(p => p.type === "final_report");
            const container = document.getElementById("final-reports");
            if (reports.length === 0) {
                container.innerHTML = '<div class="empty-state">等待 Boss Agent 汇总...</div>';
            } else {
                container.innerHTML = reports.map(r => `
                    <div style="background:#16161e;border:1px solid #22c55e;border-radius:8px;padding:16px;margin-bottom:10px;">
                        <div style="font-size:12px;color:#22c55e;margin-bottom:8px;">✓ 最终报告</div>
                        <div style="font-size:14px;color:#ccc;">${r.content}</div>
                        <div style="font-size:12px;color:#666;margin-top:8px;">hop ${r.hop_count} · ${r.sender}</div>
                    </div>
                `).join("");
            }
        }

        Promise.all([refresh(), loadProfiles(), loadPendingReviews()]);
    </script>
</body>
</html>
    """