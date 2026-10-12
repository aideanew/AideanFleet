-- database/migrations/002_goal_requirements_plan_decision.sql
-- TASK-101（current-plan §5）：goals 增加 requirements/workspace；todos 增加 plan_decision。
-- SQLite ALTER TABLE ADD COLUMN 带 NOT NULL 必须有 DEFAULT，旧数据行取默认值，无损升级。

ALTER TABLE goals ADD COLUMN requirements TEXT NOT NULL DEFAULT '';
ALTER TABLE goals ADD COLUMN workspace TEXT NOT NULL DEFAULT '';
ALTER TABLE todos ADD COLUMN plan_decision TEXT NOT NULL DEFAULT 'none';
