"""Tests for BaseCollector and dummy collector."""

import gzip
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from collectors.dummy import DummyCollector
from db.models import (
    Base,
    CollectorRun,
    PriceObservation,
    RawPayload,
    SchedulerHeartbeat,
)
from jobs.scheduler import record_heartbeat, run_collector


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
        session.commit()
    finally:
        session.close()


def test_dummy_collector_writes_price_observations(db_session):
    collector = DummyCollector()
    price_count, avail_count = collector.run(db_session)

    assert price_count == 2
    assert avail_count == 0

    rows = db_session.query(PriceObservation).all()
    assert len(rows) == 2
    assert all(row.price_per_gpu_hour_usd > 0 for row in rows)
    assert all(row.observed_at is not None for row in rows)


def test_dummy_collector_stores_raw_payload(db_session):
    collector = DummyCollector()
    collector.run(db_session)

    payloads = db_session.query(RawPayload).all()
    assert len(payloads) == 1
    data = json.loads(gzip.decompress(payloads[0].payload_gzip))
    assert data["dummy"] is True


def test_run_collector_logs_collector_run(db_session, monkeypatch):
    from jobs import scheduler as scheduler_module

    def fake_get_session():
        from contextlib import contextmanager

        @contextmanager
        def _session():
            try:
                yield db_session
            finally:
                pass

        return _session()

    monkeypatch.setattr(scheduler_module, "get_session", fake_get_session)

    run_collector(DummyCollector())

    runs = db_session.query(CollectorRun).all()
    assert len(runs) == 1
    assert runs[0].status == "success"
    assert runs[0].price_rows_written == 2


def test_record_heartbeat(db_session, monkeypatch):
    from jobs import scheduler as scheduler_module

    def fake_get_session():
        from contextlib import contextmanager

        @contextmanager
        def _session():
            try:
                yield db_session
            finally:
                pass

        return _session()

    monkeypatch.setattr(scheduler_module, "get_session", fake_get_session)

    record_heartbeat()

    heartbeats = db_session.query(SchedulerHeartbeat).all()
    assert len(heartbeats) == 1
    assert heartbeats[0].message == "alive"
