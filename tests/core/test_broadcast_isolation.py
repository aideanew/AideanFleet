"""broadcast 项目过滤与事件归属守卫单测（R4，缺陷③）。

覆盖：
- _broadcast_targets：无 project 全员广播；带 project 只发对应连接；未绑定项目的连接不收到定向消息。
- _event_broadcast_payload：空 project 的 task_update / chat_message 返回 None（不广播）；
  全局事件（mode:changed 等）与带 project 的任务事件正常通过。
"""

from fleet.console import server as console_server


def _register(ws, project):
    console_server._connections.add(ws)
    console_server._connections_project[ws] = project


def test_broadcast_targets_without_project_goes_to_all():
    a, b, c = object(), object(), object()
    _register(a, "P-001")
    _register(b, "P-002")
    _register(c, "")  # 未绑定项目的连接
    try:
        targets = console_server._broadcast_targets({"type": "config_changed"})
        assert set(targets) == {a, b, c}
    finally:
        console_server._connections.clear()
        console_server._connections_project.clear()


def test_broadcast_targets_with_project_filters_others():
    a, b, c = object(), object(), object()
    _register(a, "P-001")
    _register(b, "P-002")
    _register(c, "")
    try:
        targets = console_server._broadcast_targets({"type": "plan_update", "project": "P-001"})
        assert targets == [a]
    finally:
        console_server._connections.clear()
        console_server._connections_project.clear()


def test_unattributed_task_event_is_not_broadcast():
    row = {"seq": 1, "action": "task:done", "project": None, "taskId": "TRIGGER-CHECK-001"}
    assert console_server._event_broadcast_payload(row) is None


def test_unattributed_chat_event_is_not_broadcast():
    row = {"seq": 2, "action": "chat", "project": "", "summary": "hello"}
    assert console_server._event_broadcast_payload(row) is None


def test_global_mode_event_still_broadcasts():
    row = {"seq": 3, "action": "mode:changed", "project": None, "extra": {"from": "step", "to": "auto"}}
    payload = console_server._event_broadcast_payload(row)
    assert payload is not None
    assert payload["type"] == "notification"
    assert payload["project"] == ""


def test_attributed_task_event_broadcasts_with_project():
    row = {"seq": 4, "action": "task:done", "project": "P-008", "taskId": "P-008-T04"}
    payload = console_server._event_broadcast_payload(row)
    assert payload is not None
    assert payload["type"] == "task_update"
    assert payload["project"] == "P-008"
