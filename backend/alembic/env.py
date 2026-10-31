from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import app.models  # noqa — ensure all models are imported for autogenerate
from app.database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


import os

def run_migrations_offline():
    url = os.environ.get("DATABASE_URL_SYNC") or config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    section = config.get_section(config.config_ini_section)
    if os.environ.get("DATABASE_URL_SYNC"):
        section["sqlalchemy.url"] = os.environ["DATABASE_URL_SYNC"]
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
