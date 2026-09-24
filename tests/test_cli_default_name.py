"""CLI 启动默认项目名应从项目路径推导（大纲 L1-D 4.4）。"""

import fleet.launcher.cli_start as cli_start


def test_default_project_name_derives_from_path():
    assert cli_start.default_project_name("E:/Demo/Test09171500") == "Test09171500"
    assert cli_start.default_project_name("E:\\Code\\AideanFleet\\") == "AideanFleet"


def test_default_project_name_falls_back_when_empty():
    assert cli_start.default_project_name("") == "AideanFleet"
    assert cli_start.default_project_name("   ") == "AideanFleet"
