from datetime import date, timedelta

from app.extensions import db
from app.models import (
    AppSetting,
    DocumentRevisionRequest,
    RiskRecord,
    Suggestion,
    SuggestionEvaluation,
    SuggestionScoreParameter,
    TrainingParticipant,
    TrainingRecord,
)
from app.routes import (
    DOCUMENT_REVISION_PENDING_STATUS,
    SUGGESTION_IN_EVALUATION_STATUS,
)
from app.seed import ensure_runtime_schema

from .helpers import create_company, create_user, login, make_document


def test_assigned_tasks_lists_training_and_badge_uses_same_pool(client):
    company = create_company("361")
    manager = create_user(
        "training-manager",
        company=company,
        permissions=("training.view", "training.manage"),
    )
    participant = create_user(
        "training-participant",
        company=company,
        permissions=("training.view",),
    )
    training = TrainingRecord(
        company_id=company.id,
        training_no="EGT-2026-0001",
        title="Dokuman okuma gorevi",
        training_type="Eğitim",
        due_date=date.today() + timedelta(days=3),
        status="Planlandı",
        created_by_user_id=manager.id,
    )
    db.session.add(training)
    db.session.flush()
    db.session.add(
        TrainingParticipant(
            company_id=company.id,
            training_id=training.id,
            user_id=participant.id,
            status="Atandı",
        )
    )
    db.session.commit()

    login(client, participant)
    response = client.get("/uzerime-atananlar?module=training")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Dokuman okuma gorevi" in body
    assert "EGT-2026-0001" in body
    assert 'class="assigned-count-badge">1</span>' in body


def test_assigned_tasks_scopes_risk_owner_to_current_company(client):
    company_a = create_company("362")
    company_b = create_company("363")
    owner = create_user(
        "risk-owner",
        company=company_a,
        permissions=("risk.view",),
    )
    foreign_owner = create_user(
        "foreign-risk-owner",
        company=company_b,
        permissions=("risk.view",),
    )
    db.session.add_all(
        [
            RiskRecord(
                company_id=company_a.id,
                risk_no="RSK-2026-0001",
                title="Gorunen risk gorevi",
                status="Açık",
                likelihood=4,
                severity=5,
                owner_user_id=owner.id,
                due_date=date.today(),
            ),
            RiskRecord(
                company_id=company_b.id,
                risk_no="RSK-2026-0002",
                title="Gorunmeyen risk gorevi",
                status="Açık",
                likelihood=4,
                severity=5,
                owner_user_id=foreign_owner.id,
                due_date=date.today(),
            ),
        ]
    )
    db.session.commit()

    login(client, owner)
    response = client.get("/uzerime-atananlar?module=risk")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Gorunen risk gorevi" in body
    assert "Gorunmeyen risk gorevi" not in body


def test_document_revision_request_becomes_manager_task_and_creator_record(app, client):
    company = create_company("364")
    manager = create_user(
        "document-manager",
        company=company,
        permissions=("documents.view", "documents.manage"),
    )
    requester = create_user(
        "document-requester",
        company=company,
        permissions=("documents.view",),
    )
    document = make_document(app, company, document_code="PR.55", title="Revizyonlu dokuman")
    revision_request = DocumentRevisionRequest(
        company_id=company.id,
        document_id=document.id,
        requested_by_user_id=requester.id,
        status=DOCUMENT_REVISION_PENDING_STATUS,
        explanation="Talep gorev aciklamasi",
    )
    db.session.add(revision_request)
    db.session.commit()

    login(client, manager)
    manager_response = client.get("/uzerime-atananlar?module=document_revision")

    assert manager_response.status_code == 200
    manager_body = manager_response.get_data(as_text=True)
    assert "PR.55 Revizyon Talebi" in manager_body
    assert "Talep gorev aciklamasi" in manager_body

    login(client, requester)
    creator_response = client.get(
        "/uzerime-atananlar?scope=created&module=document_revision"
    )

    assert creator_response.status_code == 200
    assert "PR.55 Revizyon Talebi" in creator_response.get_data(as_text=True)


def test_suggestion_evaluator_only_sees_waiting_evaluations(client):
    company = create_company("365")
    creator = create_user("suggestion-creator", company=company)
    evaluator = create_user(
        "suggestion-evaluator",
        company=company,
        permissions=("suggestions.evaluate",),
    )
    parameter = SuggestionScoreParameter(
        company_id=company.id,
        name="Kritiklik",
        score=15,
        sort_order=1,
        is_active=True,
    )
    suggestion = Suggestion(
        company_id=company.id,
        suggestion_number=1,
        suggestion_date=date.today(),
        department="Kalite",
        owner_name="Oneri sahibi",
        definition="Bekleyen degerlendirme gorevi",
        status=SUGGESTION_IN_EVALUATION_STATUS,
        qdms_no="QDMS-2026-0001",
        created_by_user_id=creator.id,
    )
    db.session.add_all([parameter, suggestion])
    db.session.commit()

    login(client, evaluator)
    response = client.get("/uzerime-atananlar?module=suggestion")

    assert response.status_code == 200
    assert "Bekleyen degerlendirme gorevi" in response.get_data(as_text=True)

    db.session.add(
        SuggestionEvaluation(
            company_id=company.id,
            suggestion_id=suggestion.id,
            parameter_id=parameter.id,
            parameter_name=parameter.name,
            parameter_multiplier=parameter.score,
            evaluator_department=evaluator.full_name,
            evaluator_user_id=evaluator.id,
            rating=5,
        )
    )
    db.session.commit()

    second_response = client.get("/uzerime-atananlar?module=suggestion")

    assert second_response.status_code == 200
    assert "Bekleyen degerlendirme gorevi" not in second_response.get_data(as_text=True)


def test_runtime_schema_marks_month1_tasks_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:month1_tasks")
    assert setting is not None
    assert setting.value == "1"
