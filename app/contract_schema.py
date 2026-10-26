"""Runtime schema path used by existing installations."""

from .extensions import db
from .contract_models import ContractFile, ContractRecord


def ensure_contract_schema():
    ContractRecord.__table__.create(bind=db.engine, checkfirst=True)
    ContractFile.__table__.create(bind=db.engine, checkfirst=True)
