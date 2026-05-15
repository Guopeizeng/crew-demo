# Crew Demo - SPEC

> **版本**: v2.0 通用框架版
> **定位**: 零硬编码 Pheromone 框架，任何人可下载使用

---

## 一句话定位

**Pheromone Chain Framework** — 让信息自己知道去哪。

---

## 核心设计

### Pheromone 模型

```json
{
  "id": "abc12345",
  "type": "user_defined_string",
  "sender": "agent_001",
  "targets": ["agent_002", "agent_003"],
  "content": "Hello World",
  "parent_pheromone_id": null,
  "hop_count": 0,
  "timestamp": "2026-05-15T10:00:00Z",
  "metadata": {}
}
```

### Agent 模型

```json
{
  "agent_id": "agent_001",
  "name": "Agent Alpha",
  "role": "worker",
  "specialty": "",
  "peer_eps": [],
  "judgment_criteria": []
}
```

### Hook 机制

当某 type 的 pheromone 创建时，自动触发预设的 reply action。

```json
{
  "on_create": {
    "task": {
      "action": "reply",
      "sender": "agent_002",
      "reply_type": "response",
      "targets": ["agent_001"],
      "content": "Auto response"
    }
  }
}
```

---

## 安全协议

| 漏洞 | 协议 | 状态 |
|------|------|------|
| Pheromone Storm | hop_count ≥ 5 → timeout | ✅ |
| 僵尸信息素 | pending > 600s → DLQ | ✅ |
| 身份伪造 | X-Agent-ID 强制验证 | ✅ |
| 并发双花 | 全局写锁 | ✅ |

---

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/agents` | GET/POST | 获取/注册 agent |
| `/api/agents/<id>` | DELETE/PUT | 删除/更新 agent |
| `/api/pheromones` | GET/POST | 获取/创建 pheromone |
| `/api/chain/<id>` | GET | 链路追溯 |
| `/api/dlq` | GET | 死信队列 |
| `/api/hooks` | GET/PUT | 获取/更新 hook 配置 |
| `/api/reset` | POST | 重置 |

---

## 配置

- `config/agents.json` — agent 列表
- `config/hooks.json` — hook 规则

---

## 不做的事

- 硬编码角色
- 内置业务逻辑
- 用户认证
- 多租户