"""应用层：把 core 的能力暴露给具体的用户界面。

当前只有 CLI（`app.cli`）；M2 会加入 `app.api`（FastAPI + SSE），
M3 加入 `app.desktop`（pywebview 开窗）。三者共用同一套 core 与事件契约。
"""
