"""只读产物端点：能取数、且**取不出去**（路径穿越 / 非法名字必须被挡）。

⚠️ 反向用例是重点 —— 只测"正常能读"的端点测试等于没测安全。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.api import eval_api
from src.ui import logs_reader as logs


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    """把产物目录指向临时目录（⛔ 不依赖 logs/ 里的真实产物）。"""
    monkeypatch.setattr(logs, "LOGS_DIR", tmp_path)
    app = FastAPI()
    app.include_router(eval_api.router)
    return TestClient(app)


def test_list_and_get_artifact(client, tmp_path: Path):
    (tmp_path / "sample.json").write_text(
        json.dumps({"cfg": {"kb": "stress"}, "results": {}}), encoding="utf-8"
    )

    # ⚠️ 形状与 dev server 插件一致：`{files: [...]}`
    listed = client.get("/eval/index")
    assert listed.status_code == 200
    assert listed.json()["files"] == ["sample.json"]
    assert client.get("/eval").json()["files"] == ["sample.json"]

    got = client.get("/eval/sample.json")
    assert got.status_code == 200
    assert got.json()["cfg"]["kb"] == "stress"


def test_missing_artifact_is_404_not_empty(client):
    """⭐ 缺失必须报 404 —— 若返回空表，看板会把它读成"结果就是 0"。"""
    assert client.get("/eval/nope.json").status_code == 404


def test_bad_json_is_404(client, tmp_path: Path):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert client.get("/eval/broken.json").status_code == 404


@pytest.mark.parametrize("name", [
    "../secret.json",          # 上跳
    "sub/dir.json",            # 子目录
    "notes.txt",               # 非 .json
    ".hidden.json",            # 隐藏文件（正则要求首字符是字母数字）
    "..\\win.json",            # 反斜杠
])
def test_illegal_names_are_rejected(name: str):
    """⭐ 反向用例：这些名字必须被 400 挡下，且不发生任何读盘。"""
    with pytest.raises(HTTPException) as ei:
        eval_api._safe_path(name)
    assert ei.value.status_code == 400


def test_empty_logs_dir_lists_nothing(client, tmp_path: Path):
    """目录不存在 = 新部署的正常状态（空表，不是 500）。"""
    assert client.get("/eval/index").json()["files"] == []
