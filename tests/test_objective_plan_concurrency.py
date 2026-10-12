from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
from threading import Barrier

from tests.test_objective_plan_migration import (
    HEAD, insert_link, make_app, migrate, seed_minimal,
)


def test_independent_writers_cannot_create_two_plans_for_one_goal(tmp_path):
    path = tmp_path / 'concurrent-plans.db'
    seed_minimal(path)
    app, database = make_app(path)
    with app.app_context():
        try:
            migrate(app, 'upgrade', HEAD)
        finally:
            database.session.remove()
            database.engine.dispose()
    ready = Barrier(2)

    def create(project_id):
        with closing(sqlite3.connect(path, timeout=10)) as connection:
            ready.wait(timeout=10)
            try:
                insert_link(connection, project_id=project_id)
                connection.commit()
                return 'created'
            except sqlite3.IntegrityError:
                connection.rollback()
                return 'conflict'

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(create, (1, 4))) == ['conflict', 'created']
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute('SELECT count(*) FROM objective_plan_links').fetchone() == (1,)
        assert connection.execute('PRAGMA integrity_check').fetchone() == ('ok',)
