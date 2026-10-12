# 测试运行说明（CORE-03）

1. 创建虚拟环境：`python -m venv .venv`（激活：Windows `.venv\Scripts\activate` / bash `source .venv/Scripts/activate`）
2. 安装依赖：`pip install -r requirements.txt`
3. 运行全部测试：`python -m pytest tests -q`（预期全绿，0 failed）
