"""预算分层、并发扣款与事务回滚的离线回归。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from fleet.governance import store
from fleet.governance.budget import BudgetManager


@pytest.fixture
def budget_db(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "_db_path", tmp_path / "governance.db")
    store.init_db()
    return store


def test_same_scope_keeps_layers_separate(budget_db):
    budget_db.upsert_budget("task", "same", limit_tokens=10)
    budget_db.upsert_budget("project", "same", limit_tokens=100)
    status = BudgetManager().get_status(task_id="same", project_id="same")
    assert status["task"]["limit_tokens"] == 10
    assert status["project"]["limit_tokens"] == 100


def test_setting_limit_and_reset_preserve_other_fields(budget_db):
    budget_db.upsert_budget("task", "T", used_tokens=7, limit_tokens=100, action="warn")
    manager = BudgetManager()
    manager.set_limit("task", "T", 200, action="warn")
    assert budget_db.get_budget("task", "T")["used_tokens"] == 7
    manager.reset("task", "T")
    row = budget_db.get_budget("task", "T")
    assert (row["used_tokens"], row["limit_tokens"], row["action"]) == (0, 200, "warn")


def test_concurrent_managers_do_not_lose_consumption(budget_db):
    managers = [BudgetManager() for _ in range(8)]
    for manager in managers:
        manager.get_status(task_id="T", project_id="P")
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda m: m.consume(1, task_id="T", project_id="P"), managers))
    for level, scope in [("task", "T"), ("project", "P"), ("daily", date.today().isoformat())]:
        assert budget_db.get_budget(level, scope)["used_tokens"] == 8


def test_consumption_rolls_back_all_layers(budget_db):
    manager = BudgetManager()
    manager.get_status(task_id="T", project_id="P")
    conn = budget_db._get_conn()
    with conn:
        conn.execute("""CREATE TRIGGER fail_project BEFORE UPDATE ON governance_budget
                     WHEN NEW.level = 'project' BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    conn.close()
    with pytest.raises(Exception, match="test failure"):
        manager.consume(3, task_id="T", project_id="P")
    for level, scope in [("task", "T"), ("project", "P"), ("daily", date.today().isoformat())]:
        assert budget_db.get_budget(level, scope)["used_tokens"] == 0


@pytest.mark.parametrize("tokens", [-1, 1.5, True])
def test_invalid_consumption_rejected(budget_db, tokens):
    with pytest.raises(ValueError):
        BudgetManager().consume(tokens, task_id="T")
