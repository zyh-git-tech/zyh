## [20:25] - 配置变更 / 数据库迁移: 增加 Render PostgreSQL 一次性迁移流程

- **文件**: README.md, scripts/migrate_sqlite_to_postgres.py, tests/test_migration.py
- **决策**: 共享设备/SOP 导入目标库；诊断、Agent、预测、工单、案例和反馈统一归属 zyh；目标库非空时必须显式使用 --replace。
- **验证**: 32 项 pytest、smoke_test.py、ruff、git diff --check、SQLite 迁移演练通过；已推送 main。
