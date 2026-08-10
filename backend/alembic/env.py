from logging.config import fileConfig

from sqlalchemy import Connection, engine_from_config, pool

from alembic import context
from app.core.config import Settings
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = Settings()
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def prepare_sqlite_migration_connection(connection: Connection) -> None:
    connection.exec_driver_sql("PRAGMA foreign_keys = ON")
    foreign_keys_enabled = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
    if foreign_keys_enabled != 1:
        raise RuntimeError("Alembic SQLite 连接未能启用外键约束")

    violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        details = "; ".join(str(tuple(row)) for row in violations)
        raise RuntimeError(f"数据库存在外键违规，停止迁移：{details}")

    # 结束 PRAGMA 查询触发的隐式事务，确保后续迁移从清晰事务边界开始。
    connection.commit()


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        prepare_sqlite_migration_connection(connection)
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
