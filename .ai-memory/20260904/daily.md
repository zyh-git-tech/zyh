## [20:25] - 配置变更 / 数据库迁移: 增加 Render PostgreSQL 一次性迁移流程

- **文件**: README.md, scripts/migrate_sqlite_to_postgres.py, tests/test_migration.py
- **决策**: 共享设备/SOP 导入目标库；诊断、Agent、预测、工单、案例和反馈统一归属 zyh；目标库非空时必须显式使用 --replace。
- **验证**: 32 项 pytest、smoke_test.py、ruff、git diff --check、SQLite 迁移演练通过；已推送 main。

## [21:43] - 配置变更 / 部署: 完成 Render 管理员环境变量配置并触发生产部署

- **文件**: Render Web Service 环境变量（ADMIN_USERNAME、ADMIN_PASSWORD_HASH）
- **决策**: 使用临时管理员账号 admin，密码为用户确认的 ChangeMe_2026!；凭据未写入仓库。
- **验证**: 构建成功，Gunicorn 启动，公网 `/healthz` 返回 200；`/login`、`/register` 可访问，管理员登录及右上角账号操作可见。
