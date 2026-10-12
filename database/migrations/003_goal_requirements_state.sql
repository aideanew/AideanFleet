-- database/migrations/003_goal_requirements_state.sql
-- P3（需求澄清/冻结）：goals 增加 requirements_state。
-- 取值：'draft'（可追加澄清，未触发规划）| 'frozen'（需求已锁定，规划已触发）。
-- 旧行默认 'frozen'：001/002 时代的 goal 均由 create_goal_with_plan 自动出计划，需求即视为已锁定，无损升级。

ALTER TABLE goals ADD COLUMN requirements_state TEXT NOT NULL DEFAULT 'frozen';
