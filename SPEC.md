# Crew Demo - 周报聚合场景

> **版本**: v0.1 最小可演示版
> **目标**: 跑通"周报聚合"端到端场景，证明 Pheromone 链的价值

---

## 一句话定位

**信息自己知道去哪，Crew Pro 让周报自动找到该看到的人。**

---

## 场景描述

```
Human A（员工）发周报 
  → Boss Agent 收到 
  → Boss Agent 自动生成部门周报 
  → 分发给 Human B（老板）+ Human C（HR）
```

---

## Pheromone 链设计

### P1 - 员工提交周报

```json
{
  "id": "p1",
  "type": "weekly_report",
  "sender": "employee_zeng",
  "target": "boss_agent",
  "content": "本周完成了用户调研、V1原型、团队周会协调",
  "judgment_status": "pending",
  "timestamp": "2026-05-14T10:00:00Z"
}
```

### P2 - Boss Agent 生成部门周报（自动）

```json
{
  "id": "p2",
  "type": "weekly_digest",
  "sender": "boss_agent",
  "targets": ["manager_peng", "hr_li"],
  "content": "部门周报汇总：3人提交，1人缺席。主要进展：用户调研完成，V1原型启动。",
  "parent_pheromone_id": "p1",
  "judgment_status": "pending",
  "timestamp": "2026-05-14T10:00:30Z"
}
```

### P3 - 老板审批

```json
{
  "id": "p3",
  "type": "approval",
  "sender": "manager_peng",
  "target": "p2",
  "content": "已阅，本周进展正常",
  "judgment_status": "approved",
  "parent_pheromone_id": "p2",
  "timestamp": "2026-05-14T10:05:00Z"
}
```

### P4 - HR 归档

```json
{
  "id": "p4",
  "type": "approval",
  "sender": "hr_li",
  "target": "p2",
  "content": "已归档HR系统",
  "judgment_status": "approved",
  "parent_pheromone_id": "p2",
  "timestamp": "2026-05-14T10:06:00Z"
}
```

---

## 信息流图

```
[增] ──── P1 ────→ [Boss Agent]
                          │
                    自动生成 P2
                          │
              ┌───────────┴───────────┐
              ↓                       ↓
        [老板] P3                  [HR] P4
```

---

## 参与者

| ID | Role | EP | 说明 |
|----|------|-----|------|
| employee_zeng | 员工 | EP001 | 提交周报的普通员工 |
| boss_agent | Boss Agent | EP002 | 自动汇总周报 |
| manager_peng | 老板 | EP003 | 审批部门周报 |
| hr_li | HR | EP004 | 归档HR系统 |

---

## 技术方案

- **语言**: Python 3.14+
- **框架**: Flask
- **数据库**: SQLite（单文件）
- **LLM**: DeepSeek（默认）/ OpenAI
- **前端**: 单页 HTML + Vanilla JS（无框架）

---

## 验收标准

1. [ ] 员工提交周报后，Boss Agent 自动生成部门周报
2. [ ] 部门周报自动分发给老板和HR
3. [ ] 老板和HR可以审批，信息链路可追溯
4. [ ] 能截图展示 Pheromone 链的全流程
5. [ ] Demo UI 让人一眼看懂价值

---

## 不做的事

- 多租户
- 插件体系
- 通用路由引擎
- 用户认证