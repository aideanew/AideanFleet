"""这是什么：Fleet Kernel —— 单写者状态内核（P1，对标 LoopX：todo + claim/lease + successor + quota）。
怎么用：
    k = Kernel("data/kernel.db")
    gid = k.create_goal("做一个网站")
    tid = k.create_todo(gid, kind="exec", title="搭骨架", role="fe-1", verify=["pnpm build"])
    k.claim(tid, worker="w1")                       # open→claimed，租约 15min，登记 attempt
    k.mark_running(tid, "w1"); k.mark_verifying(tid, "w1")
    k.transition(tid, TurnResult(verdict="done"))   # 唯一写回入口（verify 通过后调用）
设计铁律：
- 所有状态变更只走 Kernel 的方法（claim/mark_*/transition/requeue），禁止外部 UPDATE；
- events 表在同一事务内追加（outbox），JSONL 只是导出；
- 验证通过并写回才算进度，写回 done 后才计费（quota.used+1）；
- 返工 = successor todo（同一 lineage）；同一 lineage 轮数超限 → needs_user；
- 租约过期由 requeue_expired_leases 回收 → worker 被 kill 后可从断点接续；
- 本包不 import 任何上层包（tests/architecture/test_import_boundaries.py 守门）。
"""

from __future__ import annotations

import itertools
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import state as st
from . import store

DEFAULT_LEASE_SECONDS = 15 * 60
DEFAULT_LINEAGE_LIMIT = 4  # 同一 lineage 最大 attempt 轮数，超过 → needs_user

_SEQ = itertools.count(1)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _day() -> str:
    return datetime.now().strftime("%Y-%m-%d")


class KernelError(Exception):
    """内核状态/写回非法操作。"""


class Kernel:
    """Todo 内核：goal/todo/claim/lease/attempts/quota/events 的唯一写入口。"""

    def __init__(
        self,
        db_path: str | Path,
        *,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        lineage_limit: int = DEFAULT_LINEAGE_LIMIT,
    ) -> None:
        self.db_path = str(db_path)
        self.lease_seconds = lease_seconds
        self.lineage_limit = lineage_limit
        store.init_db(self.db_path)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _conn(self):
        return store.connect(self.db_path)

    def _event(self, conn, kind: str, todo_id: str = "", goal_id: str = "", **payload) -> None:
        conn.execute(
            "INSERT INTO events (ts, kind, todo_id, goal_id, payload) VALUES (?,?,?,?,?)",
            (_now_iso(), kind, todo_id, goal_id, json.dumps(payload, ensure_ascii=False)),
        )

    @staticmethod
    def _todo_row(row) -> dict[str, Any]:
        data = dict(row)
        for key in ("depends_on", "verify", "allowed_files"):
            raw = data.get(key) or "[]"
            try:
                data[key] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                data[key] = []
        return data

    def _get(self, conn, todo_id: str) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM todos WHERE id=?", (todo_id,)).fetchone()
        if row is None:
            raise KeyError(f"todo 不存在: {todo_id}")
        return self._todo_row(row)

    @staticmethod
    def _new_id() -> str:
        return f"T-{int(time.time() * 1000):x}-{next(_SEQ)}"

    # ------------------------------------------------------------------
    # goal / todo 创建
    # ------------------------------------------------------------------

    def create_goal(self, title: str, goal_id: str | None = None) -> str:
        gid = goal_id or f"G-{int(time.time() * 1000):x}-{next(_SEQ)}"
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO goals (id, title, status, created_at) VALUES (?,?,?,?)",
                (gid, title, "active", _now_iso()),
            )
            self._event(conn, "goal:created", goal_id=gid, title=title)
        return gid

    def create_todo(
        self,
        goal_id: str,
        *,
        kind: str = "exec",
        title: str,
        role: str = "",
        depends_on: list[str] | None = None,
        allowed_files: list[str] | str = "",
        verify: list[str] | None = None,
        done_when: str = "",
        packet: str = "",
        workspace: str = "",
        todo_id: str | None = None,
    ) -> str:
        if kind not in st.TODO_KINDS:
            raise KernelError(f"非法 todo kind: {kind}（允许 {st.TODO_KINDS}）")
        tid = todo_id or self._new_id()
        if isinstance(allowed_files, str):
            allowed_files = [item.strip() for item in allowed_files.split(",") if item.strip()]
        with self._conn() as conn:
            self._get_goal(conn, goal_id)  # 目标必须存在
            conn.execute(
                """INSERT INTO todos
                   (id, goal_id, kind, title, role, depends_on, allowed_files, verify,
                    done_when, packet, workspace, status, lineage, attempt_count, successor_of,
                    claimed_by, claim_expires_at, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,'','',0,?,?)""",
                (
                    tid, goal_id, kind, title, role,
                    json.dumps(depends_on or []), json.dumps(list(allowed_files)),
                    json.dumps(verify or []), done_when, packet, workspace,
                    st.OPEN, tid, _now_iso(), _now_iso(),
                ),
            )
            self._event(conn, "todo:created", todo_id=tid, goal_id=goal_id,
                        todo_kind=kind, title=title, role=role)
        return tid

    def _get_goal(self, conn, goal_id: str) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
        if row is None:
            raise KeyError(f"goal 不存在: {goal_id}")
        return dict(row)

    # ------------------------------------------------------------------
    # claim / lease
    # ------------------------------------------------------------------

    def _deps_done(self, conn, todo: dict[str, Any]) -> bool:
        for dep in todo["depends_on"]:
            row = conn.execute("SELECT status FROM todos WHERE id=?", (dep,)).fetchone()
            if row is None or row["status"] != st.DONE:
                return False
        return True

    @staticmethod
    def _parse_roots(patterns: list[str]) -> set[str]:
        """allowed_files 归一化为顶层目录/文件名集合（并行冲突判断用）。"""
        roots: set[str] = set()
        for pattern in patterns or []:
            norm = str(pattern).replace("\\", "/").strip("/")
            if norm:
                roots.add(norm.split("/")[0])
        return roots

    def _quota_left(self, conn, key: str) -> bool:
        row = conn.execute("SELECT * FROM quota WHERE key=?", (key,)).fetchone()
        if row is None or row["limit_per_day"] <= 0:
            return True
        used = row["used"] if row["day"] == _day() else 0
        return used < row["limit_per_day"]

    def claimable(self, role: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
        """当前可认领的 todo：依赖完成 + allowed_files 不与在跑任务相交 + 额度未耗尽，FIFO。

        进入前先回收过期租约（kill-safe：worker 死亡后其任务自动回到可认领队列）。
        """
        self.requeue_expired_leases()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM todos WHERE status=? ORDER BY created_at, id", (st.OPEN,)
            ).fetchall()
            active = conn.execute(
                "SELECT allowed_files, id FROM todos WHERE status IN (?,?,?)",
                (st.CLAIMED, st.RUNNING, st.VERIFYING),
            ).fetchall()
            active_roots = [(r["id"], self._parse_roots(self._todo_row(r)["allowed_files"]))
                            for r in active]
            out = []
            for row in rows:
                todo = self._todo_row(row)
                if role and todo["role"] and todo["role"] != role:
                    continue
                if kind and todo["kind"] != kind:
                    continue
                if not self._deps_done(conn, todo):
                    continue
                mine = self._parse_roots(todo["allowed_files"])
                if mine and any(mine & theirs for _, theirs in active_roots):
                    continue
                if not self._quota_left(conn, "global") or not self._quota_left(conn, todo["role"]):
                    continue
                out.append(todo)
            return out

    def claim(self, todo_id: str, worker: str, lease_seconds: int | None = None,
              harness: str = "", model: str = "") -> dict[str, Any]:
        """open→claimed：写认领人与租约；登记一条未闭合 attempt（harness/model/started_at）。"""
        lease = lease_seconds if lease_seconds is not None else self.lease_seconds
        with self._conn() as conn:
            todo = self._get(conn, todo_id)
            if todo["status"] != st.OPEN:
                raise KernelError(f"todo {todo_id} 状态为 {todo['status']}，不可认领（需 open）")
            conn.execute(
                """UPDATE todos SET status=?, claimed_by=?, claim_expires_at=?,
                   attempt_count=attempt_count+1, updated_at=? WHERE id=?""",
                (st.CLAIMED, worker, time.time() + lease, _now_iso(), todo_id),
            )
            conn.execute(
                """INSERT INTO attempts (todo_id, harness, model, started_at)
                   VALUES (?,?,?,?)""",
                (todo_id, harness, model, _now_iso()),
            )
            self._event(conn, "todo:claimed", todo_id=todo_id, goal_id=todo["goal_id"],
                        worker=worker, lease_s=lease, harness=harness, model=model)
        return self.get_todo(todo_id)

    def renew_lease(self, todo_id: str, worker: str, lease_seconds: int | None = None) -> None:
        """执行中续约（流式输出心跳）。仅认领人本人可续。"""
        lease = lease_seconds if lease_seconds is not None else self.lease_seconds
        with self._conn() as conn:
            todo = self._get(conn, todo_id)
            if todo["claimed_by"] != worker:
                raise KernelError(f"todo {todo_id} 不属于 worker {worker}，不能续约")
            if todo["status"] not in (st.CLAIMED, st.RUNNING, st.VERIFYING):
                raise KernelError(f"todo {todo_id} 状态 {todo['status']} 无需续约")
            conn.execute(
                "UPDATE todos SET claim_expires_at=?, updated_at=? WHERE id=?",
                (time.time() + lease, _now_iso(), todo_id),
            )

    def requeue_expired_leases(self) -> list[str]:
        """租约到期（worker 死亡/卡死）→ 回收为 open，事件 todo:lease_expired。"""
        reclaimed: list[str] = []
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id FROM todos WHERE status IN (?,?,?) AND claim_expires_at>0 AND claim_expires_at<?",
                (st.CLAIMED, st.RUNNING, st.VERIFYING, time.time()),
            ).fetchall()
            for row in rows:
                tid = row["id"]
                conn.execute(
                    "UPDATE todos SET status=?, claimed_by='', claim_expires_at=0, updated_at=? WHERE id=?",
                    (st.OPEN, _now_iso(), tid),
                )
                self._close_open_attempt(conn, tid, turn_result="lease_expired")
                self._event(conn, "todo:lease_expired", todo_id=tid)
                reclaimed.append(tid)
        return reclaimed

    # ------------------------------------------------------------------
    # 状态推进
    # ------------------------------------------------------------------

    def _assert_holder(self, todo: dict[str, Any], worker: str) -> None:
        if todo["claimed_by"] != worker:
            raise KernelError(f"todo {todo['id']} 认领人是 {todo['claimed_by']}，不是 {worker}")

    def mark_running(self, todo_id: str, worker: str) -> None:
        with self._conn() as conn:
            todo = self._get(conn, todo_id)
            if todo["status"] != st.CLAIMED:
                raise KernelError(f"todo {todo_id} 状态 {todo['status']}，无法进入 running")
            self._assert_holder(todo, worker)
            conn.execute(
                "UPDATE todos SET status=?, updated_at=? WHERE id=?",
                (st.RUNNING, _now_iso(), todo_id),
            )
            self._event(conn, "todo:running", todo_id=todo_id, goal_id=todo["goal_id"], worker=worker)

    def mark_verifying(self, todo_id: str, worker: str) -> None:
        with self._conn() as conn:
            todo = self._get(conn, todo_id)
            if todo["status"] != st.RUNNING:
                raise KernelError(f"todo {todo_id} 状态 {todo['status']}，无法进入 verifying")
            self._assert_holder(todo, worker)
            conn.execute(
                "UPDATE todos SET status=?, updated_at=? WHERE id=?",
                (st.VERIFYING, _now_iso(), todo_id),
            )
            self._event(conn, "todo:verifying", todo_id=todo_id, goal_id=todo["goal_id"], worker=worker)

    @staticmethod
    def _close_open_attempt(conn, todo_id: str, turn_result: str) -> None:
        conn.execute(
            """UPDATE attempts SET ended_at=?, turn_result=?
               WHERE todo_id=? AND ended_at IS NULL""",
            (_now_iso(), turn_result, todo_id),
        )

    def transition(self, todo_id: str, result: st.TurnResult) -> dict[str, Any]:
        """唯一写回入口：在真实 verify 之后调用。verdict 决定去向，attempt/事件同事务落库。

        - done:       verifying→done（无 verify 的 exec todo 必须带证据，否则拒绝写回）；
                      写回后按角色计费；goal 全部完成 → goal:done
        - successor:  关闭当前轮，新建同 lineage 的 successor todo（轮数超限 → needs_user）
        - blocked:    →blocked（等待人工/上游解除）
        - needs_user: →needs_user
        """
        if result.verdict not in st.VERDICTS:
            raise KernelError(f"非法 verdict: {result.verdict}（允许 {st.VERDICTS}）")
        with self._conn() as conn:
            todo = self._get(conn, todo_id)
            from_status = todo["status"]
            if from_status not in (st.CLAIMED, st.RUNNING, st.VERIFYING):
                raise KernelError(f"todo {todo_id} 状态 {from_status} 不可写回")
            if result.verdict == st.VERDICT_DONE and from_status != st.VERIFYING:
                raise KernelError(
                    f"todo {todo_id} 写回 done 必须处于 verifying（当前 {from_status}）——"
                    "先跑完真实 verify 再 mark_verifying"
                )
            now = _now_iso()
            goal_id = todo["goal_id"]
            evidence = result.evidence_path
            if result.verdict == st.VERDICT_DONE:
                if todo["kind"] == "exec" and not todo["verify"] and not evidence:
                    raise KernelError(
                        f"todo {todo_id} 无 verify 命令且无证据，禁止写回 done（A5：完成必须可信）"
                    )
                conn.execute(
                    "UPDATE todos SET status=?, updated_at=?, claim_expires_at=0 WHERE id=?",
                    (st.DONE, now, todo_id),
                )
                self._close_open_attempt(conn, todo_id, turn_result="done")
                conn.execute(
                    """UPDATE attempts SET exit_code=?, tokens_in=?, tokens_out=?,
                       evidence_path=?, session_id=? WHERE todo_id=? AND ended_at IS NOT NULL
                       AND turn_result='done' AND id=(SELECT MAX(id) FROM attempts WHERE todo_id=?)""",
                    (result.exit_code, result.tokens_in, result.tokens_out,
                     evidence, result.session_id, todo_id, todo_id),
                )
                self._event(conn, "todo:done", todo_id=todo_id, goal_id=goal_id,
                            note=result.note, evidence=evidence,
                            tokens_in=result.tokens_in, tokens_out=result.tokens_out)
                self._charge(conn, todo["role"] or "global")
                unfinished = conn.execute(
                    "SELECT COUNT(*) AS n FROM todos WHERE goal_id=? AND status NOT IN (?,?)",
                    (goal_id, st.DONE, st.SUPERSEDED),
                ).fetchone()["n"]
                if unfinished == 0:
                    conn.execute("UPDATE goals SET status='done' WHERE id=?", (goal_id,))
                    self._event(conn, "goal:done", goal_id=goal_id)
            elif result.verdict == st.VERDICT_SUCCESSOR:
                spec = dict(result.successor or {})
                lineage_rounds = self._lineage_attempts(conn, todo["lineage"])
                if lineage_rounds >= self.lineage_limit:
                    conn.execute(
                        "UPDATE todos SET status=?, updated_at=?, claim_expires_at=0 WHERE id=?",
                        (st.NEEDS_USER, now, todo_id),
                    )
                    self._close_open_attempt(conn, todo_id, turn_result="needs_user")
                    self._event(conn, "todo:needs_user", todo_id=todo_id, goal_id=goal_id,
                                reason=f"lineage 轮数达上限 {self.lineage_limit}", note=result.note)
                else:
                    conn.execute(
                        "UPDATE todos SET status=?, updated_at=?, claim_expires_at=0 WHERE id=?",
                        (st.SUPERSEDED, now, todo_id),
                    )
                    self._close_open_attempt(conn, todo_id, turn_result="successor")
                    new_id = spec.get("id") or self._new_id()
                    conn.execute(
                        """INSERT INTO todos
                           (id, goal_id, kind, title, role, depends_on, allowed_files, verify,
                            done_when, packet, workspace, status, lineage, attempt_count, successor_of,
                            claimed_by, claim_expires_at, created_at, updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,'',0,?,?)""",
                        (
                            new_id, goal_id, spec.get("kind", todo["kind"]),
                            spec.get("title", f"{todo['title']}（返工）"),
                            spec.get("role", todo["role"]),
                            json.dumps(spec.get("depends_on", [])),
                            json.dumps(spec.get("allowed_files", todo["allowed_files"])),
                            json.dumps(spec.get("verify", todo["verify"])),
                            spec.get("done_when", todo["done_when"]),
                            spec.get("packet", todo["packet"]),
                            spec.get("workspace", todo["workspace"]),
                            st.OPEN, todo["lineage"], todo_id, now, now,
                        ),
                    )
                    self._event(conn, "todo:successor", todo_id=todo_id, goal_id=goal_id,
                                successor=new_id, note=result.note)
            elif result.verdict == st.VERDICT_BLOCKED:
                conn.execute(
                    "UPDATE todos SET status=?, updated_at=?, claim_expires_at=0 WHERE id=?",
                    (st.BLOCKED, now, todo_id),
                )
                self._close_open_attempt(conn, todo_id, turn_result="blocked")
                self._event(conn, "todo:blocked", todo_id=todo_id, goal_id=goal_id, note=result.note)
            else:  # needs_user
                conn.execute(
                    "UPDATE todos SET status=?, updated_at=?, claim_expires_at=0 WHERE id=?",
                    (st.NEEDS_USER, now, todo_id),
                )
                self._close_open_attempt(conn, todo_id, turn_result="needs_user")
                self._event(conn, "todo:needs_user", todo_id=todo_id, goal_id=goal_id, note=result.note)
        return self.get_todo(todo_id)

    def reopen(self, todo_id: str, actor: str) -> dict[str, Any]:
        """人工动作：blocked / needs_user → open（用户决策/解除阻塞后重开）。"""
        with self._conn() as conn:
            todo = self._get(conn, todo_id)
            if todo["status"] not in (st.BLOCKED, st.NEEDS_USER):
                raise KernelError(f"todo {todo_id} 状态 {todo['status']} 不可重开")
            conn.execute(
                "UPDATE todos SET status=?, claimed_by='', claim_expires_at=0, updated_at=? WHERE id=?",
                (st.OPEN, _now_iso(), todo_id),
            )
            self._event(conn, "todo:reopened", todo_id=todo_id, goal_id=todo["goal_id"], actor=actor)
        return self.get_todo(todo_id)

    def _lineage_attempts(self, conn, lineage: str) -> int:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM attempts WHERE todo_id IN (SELECT id FROM todos WHERE lineage=?)",
            (lineage,),
        ).fetchone()
        return int(row["n"])

    # ------------------------------------------------------------------
    # quota：验证通过并写回才计费
    # ------------------------------------------------------------------

    def _charge(self, conn, key: str, amount: int = 1) -> None:
        row = conn.execute("SELECT * FROM quota WHERE key=?", (key,)).fetchone()
        day = _day()
        if row is None:
            conn.execute(
                "INSERT INTO quota (key, used, limit_per_day, day) VALUES (?,?,0,?)",
                (key, amount, day),
            )
            return
        used = row["used"] + amount if row["day"] == day else amount
        conn.execute("UPDATE quota SET used=?, day=? WHERE key=?", (used, day, key))

    def set_quota(self, key: str, limit_per_day: int) -> None:
        with self._conn() as conn:
            row = conn.execute("SELECT key FROM quota WHERE key=?", (key,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO quota (key, used, limit_per_day, day) VALUES (?,?,?,?)",
                    (key, 0, limit_per_day, _day()),
                )
            else:
                conn.execute("UPDATE quota SET limit_per_day=? WHERE key=?", (limit_per_day, key))

    def quota_remaining(self, key: str) -> int | None:
        """剩余额度；None = 无限制。"""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM quota WHERE key=?", (key,)).fetchone()
            if row is None or row["limit_per_day"] <= 0:
                return None
            used = row["used"] if row["day"] == _day() else 0
            return max(0, row["limit_per_day"] - used)

    def should_run(self) -> tuple[bool, str]:
        """调度前置判断（A1：每轮先问该不该跑）：无可执行 todo / 无额度 → 安静等待。

        可执行但额度耗尽时返回 quota_exhausted:<key>（UI 据此提示，而不是笼统的没任务）。
        """
        claimables = self.claimable()
        if claimables:
            with self._conn() as conn:
                if not self._quota_left(conn, "global"):
                    return False, "quota_exhausted:global"
            return True, "ok"
        with self._conn() as conn:
            open_roles = {r["role"] or "global" for r in conn.execute(
                "SELECT role FROM todos WHERE status=?", (st.OPEN,))}
            rows = conn.execute("SELECT key, used, limit_per_day, day FROM quota").fetchall()
        for row in rows:
            if row["limit_per_day"] > 0 and row["day"] == _day() and row["used"] >= row["limit_per_day"]:
                if row["key"] == "global" or row["key"] in open_roles:
                    return False, f"quota_exhausted:{row['key']}"
        return False, "no_runnable_todo"

    # ------------------------------------------------------------------
    # 读侧：packet / 投影 / 事件
    # ------------------------------------------------------------------

    def get_todo(self, todo_id: str) -> dict[str, Any]:
        with self._conn() as conn:
            return self._get(conn, todo_id)

    def todos(self, goal_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM todos"
        cond, args = [], []
        if goal_id:
            cond.append("goal_id=?")
            args.append(goal_id)
        if status:
            cond.append("status=?")
            args.append(status)
        if cond:
            query += " WHERE " + " AND ".join(cond)
        query += " ORDER BY created_at, id"
        with self._conn() as conn:
            return [self._todo_row(r) for r in conn.execute(query, args).fetchall()]

    def attempts_of(self, todo_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM attempts WHERE todo_id=? ORDER BY id", (todo_id,))]

    def packet_for(self, todo_id: str) -> dict[str, Any]:
        """组装执行包：目标、todo、allowed_files、验收命令、写回格式（LoopX packet 语义）。"""
        with self._conn() as conn:
            todo = self._get(conn, todo_id)
            goal = self._get_goal(conn, todo["goal_id"])
            siblings = conn.execute(
                "SELECT id, title, status FROM todos WHERE goal_id=? AND id<>? ORDER BY created_at",
                (todo["goal_id"], todo_id),
            ).fetchall()
        return {
            "todo": {
                "id": todo["id"], "kind": todo["kind"], "title": todo["title"],
                "role": todo["role"], "allowed_files": todo["allowed_files"],
                "verify": todo["verify"], "done_when": todo["done_when"],
                "attempt_count": todo["attempt_count"], "packet": todo["packet"],
                "workspace": todo["workspace"],
            },
            "goal": {"id": goal["id"], "title": goal["title"]},
            "siblings": [dict(s) for s in siblings],
            "writeback": {
                "verdicts": list(st.VERDICTS),
                "format": "fleet writeback --todo <id> --verdict <done|successor|blocked|needs_user> --note <text>",
            },
            "rules": [
                "只改 allowed_files 白名单内文件",
                "verify 命令必须真实执行并通过，禁止只声称完成",
                "完整报告经 stdout/写回 note 返回，证据由控制面落盘",
            ],
        }

    def attention(self) -> dict[str, Any]:
        """看板投影首屏数据：现在谁需要行动（待决策/运行中/阻塞/刚完成）。"""
        with self._conn() as conn:
            def fetch(sql: str, args: tuple = ()) -> list[dict[str, Any]]:
                return [self._todo_row(r) for r in conn.execute(sql, args)]

            needs_user = fetch(
                "SELECT * FROM todos WHERE status=? ORDER BY updated_at DESC", (st.NEEDS_USER,))
            running = fetch(
                "SELECT * FROM todos WHERE status IN (?,?,?) ORDER BY updated_at DESC",
                (st.CLAIMED, st.RUNNING, st.VERIFYING))
            blocked = fetch(
                "SELECT * FROM todos WHERE status=? ORDER BY updated_at DESC", (st.BLOCKED,))
            done_recent = fetch(
                "SELECT * FROM todos WHERE status=? ORDER BY updated_at DESC LIMIT 10", (st.DONE,))
            goals = [dict(r) for r in conn.execute("SELECT * FROM goals ORDER BY created_at DESC")]
            counts = {
                "needs_user": len(needs_user), "running": len(running),
                "blocked": len(blocked), "done": len(done_recent),
                "open": conn.execute(
                    "SELECT COUNT(*) AS n FROM todos WHERE status=?", (st.OPEN,)).fetchone()["n"],
                "superseded": conn.execute(
                    "SELECT COUNT(*) AS n FROM todos WHERE status=?", (st.SUPERSEDED,)).fetchone()["n"],
            }
        return {
            "counts": counts,
            "needs_user": needs_user, "running": running,
            "blocked": blocked, "done_recent": done_recent, "goals": goals,
        }

    def pending_events(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE published=0 ORDER BY seq LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_events_published(self, seqs: list[int]) -> None:
        if not seqs:
            return
        with self._conn() as conn:
            conn.executemany("UPDATE events SET published=1 WHERE seq=?", [(s,) for s in seqs])
