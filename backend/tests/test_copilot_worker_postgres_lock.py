import os
from uuid import UUID, uuid4

import psycopg
import pytest


@pytest.mark.postgres
def test_postgres_skip_locked_allows_only_one_worker_to_claim_same_step() -> None:
    dsn = os.getenv("POSTGRES_TEST_DSN") or "postgresql://app:pass@localhost:5432/eap"
    worker_a = f"worker-a-{uuid4()}"
    worker_b = f"worker-b-{uuid4()}"
    step_id = str(uuid4())

    with psycopg.connect(dsn) as setup:
        with setup.cursor() as cur:
            cur.execute(
                "create table if not exists copilot_lock_test_steps (id uuid primary key, status text not null, claimed_by text null)"
            )
            cur.execute("delete from copilot_lock_test_steps where id = %s", (step_id,))
            cur.execute(
                "insert into copilot_lock_test_steps (id, status) values (%s, 'queued')",
                (step_id,),
            )
        setup.commit()

    conn_a = psycopg.connect(dsn)
    conn_b = psycopg.connect(dsn)
    try:
        cur_a = conn_a.cursor()
        cur_b = conn_b.cursor()
        cur_a.execute("begin")
        cur_b.execute("begin")
        cur_a.execute(
            "select id from copilot_lock_test_steps where status = 'queued' order by id limit 1 for update skip locked"
        )
        claimed_a = cur_a.fetchone()
        cur_b.execute(
            "select id from copilot_lock_test_steps where status = 'queued' order by id limit 1 for update skip locked"
        )
        claimed_b = cur_b.fetchone()

        assert claimed_a == (UUID(step_id),)
        assert claimed_b is None

        cur_a.execute(
            "update copilot_lock_test_steps set status = 'running', claimed_by = %s where id = %s",
            (worker_a, step_id),
        )
        conn_a.commit()
        conn_b.rollback()

        with psycopg.connect(dsn) as verify:
            with verify.cursor() as cur:
                cur.execute(
                    "select status, claimed_by from copilot_lock_test_steps where id = %s",
                    (step_id,),
                )
                assert cur.fetchone() == ("running", worker_a)
    finally:
        conn_a.close()
        conn_b.close()
        with psycopg.connect(dsn) as cleanup:
            with cleanup.cursor() as cur:
                cur.execute("delete from copilot_lock_test_steps where id = %s", (step_id,))
            cleanup.commit()
