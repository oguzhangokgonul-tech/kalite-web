from app import db
from app.models import Suggestion, SuggestionEvaluation, SuggestionScoreParameter, User
from app.routes import SUGGESTION_COMPLETED_STATUS, SUGGESTION_IN_EVALUATION_STATUS, SUGGESTION_PENDING_APPROVAL_STATUS
from app.seed import ensure_default_users
from tests.helpers import create_company, create_user, login


def test_production_seed_does_not_create_known_accounts_or_reactivate_admin(app):
    app.config["APP_ENV"] = "production"
    admin = create_user("superadmin", role_key="viewer")
    admin.is_active = False
    db.session.commit()
    ensure_default_users(reset_passwords=False)
    assert User.query.count() == 1
    assert not admin.is_active
    assert {role.key for role in admin.roles} == {"viewer"}


def test_initial_superadmin_requires_private_strong_password(app):
    app.config.update(PASSWORD_MIN_LENGTH=10, PASSWORD_MAX_LENGTH=128)
    runner = app.test_cli_runner()
    result = runner.invoke(args=["create-superadmin"], input="short\nshort\n")
    assert result.exit_code != 0
    assert User.query.count() == 0
    result = runner.invoke(args=["create-superadmin"], input="private-strong-password\nprivate-strong-password\n")
    assert result.exit_code == 0, result.output
    user = User.query.one()
    assert user.check_password("private-strong-password")
    assert {role.key for role in user.roles} == {"super_admin"}


def test_other_staff_cannot_view_pending_or_modify_anothers_suggestion(client):
    company = create_company("SEC")
    owner = create_user("owner", company=company, role_key="department_staff")
    other = create_user("other", company=company, role_key="viewer")
    suggestion = Suggestion(company_id=company.id, created_by_user_id=owner.id,
                            owner_name=owner.full_name, definition="Original",
                            status=SUGGESTION_PENDING_APPROVAL_STATUS)
    db.session.add(suggestion)
    db.session.commit()
    path = f"/oneri-sikayet/oneri/{suggestion.id}"
    login(client, other, company)
    assert client.get(path).status_code == 403
    assert client.get(path + "/duzenle").status_code == 403
    assert client.post(path + "/duzenle", data={"definition": "Changed"}).status_code == 403
    assert client.post(path + "/sil").status_code == 403
    login(client, owner, company)
    assert client.get(path + "/duzenle").status_code == 200
    own_list = client.get("/oneri-sikayet/oneri?mine=1").get_data(as_text=True)
    assert path + "/duzenle" in own_list
    login(client, other, company)
    other_list = client.get("/oneri-sikayet/oneri?mine=1").get_data(as_text=True)
    assert path + "/duzenle" not in other_list


def test_same_name_evaluators_have_independent_scores_and_rename_does_not_duplicate(client):
    company = create_company("EVAL")
    users = [create_user(f"evaluator-{i}", company=company, role_key="department_staff",
                         full_name="Aynı İsim", permissions=("suggestions.evaluate",))
             for i in (1, 2)]
    suggestion = Suggestion(company_id=company.id, owner_name="Owner", definition="Test",
                            status=SUGGESTION_IN_EVALUATION_STATUS)
    parameter = SuggestionScoreParameter(company_id=company.id, name="Criticality", score=15,
                                         sort_order=1, is_active=True)
    db.session.add_all([suggestion, parameter])
    db.session.commit()
    path = f"/oneri-sikayet/oneri/{suggestion.id}/degerlendir"
    login(client, users[0], company)
    assert client.post(path, data={f"rating_{parameter.id}": "2"}).status_code == 302
    summary = client.get(f"/oneri-sikayet/oneri/{suggestion.id}").get_data(as_text=True)
    assert "Değerlendirme Bekliyor" in summary
    users[0].full_name = "Changed Name"
    db.session.commit()
    assert client.post(path, data={f"rating_{parameter.id}": "3"}).status_code == 302
    login(client, users[1], company)
    assert client.post(path, data={f"rating_{parameter.id}": "4"}).status_code == 302
    rows = SuggestionEvaluation.query.filter_by(suggestion_id=suggestion.id).all()
    assert len(rows) == 2
    assert {row.evaluator_user_id: row.rating for row in rows} == {users[0].id: 3, users[1].id: 4}
    assert sum(row.weighted_score for row in rows) == 105


def test_login_lockout_does_not_cross_company_boundary(app, client):
    app.config.update(LOGIN_MAX_FAILED_ATTEMPTS=2, LOGIN_LOCKOUT_MINUTES=10,
                      LOGIN_IP_MAX_FAILED_ATTEMPTS=100)
    companies = [create_company(f"login-{i}") for i in (1, 2)]
    users = [create_user("same-login", company=company, role_key="department_staff")
             for company in companies]
    for user in users:
        user.set_password("private-strong-password")
    db.session.commit()
    for _ in range(2):
        client.post("/login", data={"identity": "same-login", "password": "wrong"},
                    base_url=f"https://{companies[0].slug}.volkaportal.com")
    response = client.post("/login", data={"identity": "same-login", "password": "private-strong-password"},
                           base_url=f"https://{companies[1].slug}.volkaportal.com")
    assert response.status_code == 302
    with client.session_transaction(base_url=f"https://{companies[1].slug}.volkaportal.com") as session:
        assert session["user_id"] == users[1].id


def test_disabled_user_cannot_reuse_existing_session(client):
    company = create_company("DISABLED")
    user = create_user("disabled-session", company=company, role_key="department_staff")
    login(client, user, company)
    user.is_active = False
    db.session.commit()
    assert client.get("/").status_code == 302
    with client.session_transaction() as session:
        assert "user_id" not in session


def test_company_account_named_superadmin_cannot_access_global_admin_tools(client):
    company = create_company("RESERVED")
    user = create_user("superadmin", company=company, role_key="viewer")
    login(client, user, company)
    assert client.get("/satisa-hazirlik").status_code == 403
    assert client.get("/kurulum-sihirbazi").status_code == 403


def test_partial_evaluation_stays_pending_and_blank_removes_only_own_score(client):
    company = create_company("PARTIAL")
    users = [create_user(f"partial-{i}", company=company,
                         permissions=("suggestions.evaluate",)) for i in (1, 2)]
    parameters = [SuggestionScoreParameter(company_id=company.id, name=f"Criterion {i}",
                                           score=15 if i == 1 else -5, sort_order=i,
                                           is_active=True) for i in (1, 2)]
    suggestion = Suggestion(company_id=company.id, owner_name="Owner",
                            definition="Incomplete evaluation task",
                            status=SUGGESTION_IN_EVALUATION_STATUS)
    db.session.add_all([suggestion, *parameters])
    db.session.commit()
    path = f"/oneri-sikayet/oneri/{suggestion.id}"
    first, second = parameters
    login(client, users[0], company)
    client.post(path + "/degerlendir", data={f"rating_{first.id}": "2", f"rating_{second.id}": ""})
    assert suggestion.status == SUGGESTION_IN_EVALUATION_STATUS
    assert len(suggestion.evaluations) == 1
    assert "Değerlendirme Bekliyor" in client.get(path).get_data(as_text=True)
    assert suggestion.definition in client.get("/uzerime-atananlar?module=suggestion").get_data(as_text=True)
    full = {f"rating_{first.id}": "3", f"rating_{second.id}": "4"}
    client.post(path + "/degerlendir", data=full)
    assert suggestion.status == SUGGESTION_IN_EVALUATION_STATUS
    assert suggestion.definition not in client.get("/uzerime-atananlar?module=suggestion").get_data(as_text=True)
    login(client, users[1], company)
    client.post(path + "/degerlendir", data=full)
    assert suggestion.status == SUGGESTION_COMPLETED_STATUS

    extra = SuggestionScoreParameter(company_id=company.id, name="New criterion", score=1,
                                     sort_order=3, is_active=True)
    db.session.add(extra)
    db.session.commit()
    assert suggestion.definition in client.get("/uzerime-atananlar?module=suggestion").get_data(as_text=True)
    client.post(path + "/degerlendir", data={**full, f"rating_{extra.id}": "5"})
    assert suggestion.status == SUGGESTION_IN_EVALUATION_STATUS
    assert any(row.parameter_id == extra.id and row.evaluator_user_id == users[1].id
               for row in suggestion.evaluations)
    client.post(path + "/degerlendir", data={f"rating_{first.id}": "", f"rating_{second.id}": "4"})
    own = [row for row in suggestion.evaluations if row.evaluator_user_id == users[1].id]
    assert {row.parameter_id for row in own} == {second.id}
    assert len([row for row in suggestion.evaluations if row.evaluator_user_id == users[0].id]) == 2
    client.post(path + "/degerlendir", data={f"rating_{first.id}": "", f"rating_{second.id}": ""})
    assert not [row for row in suggestion.evaluations if row.evaluator_user_id == users[1].id]


def test_invalid_rating_rolls_back_clear_and_valid_changes(client):
    company = create_company("INVALID")
    user = create_user("invalid-evaluator", company=company, permissions=("suggestions.evaluate",))
    parameters = [SuggestionScoreParameter(company_id=company.id, name=f"Item {i}", score=1,
                                           sort_order=i, is_active=True) for i in (1, 2, 3)]
    suggestion = Suggestion(company_id=company.id, owner_name="Owner", definition="Atomic test",
                            status=SUGGESTION_IN_EVALUATION_STATUS)
    db.session.add_all([suggestion, *parameters])
    db.session.commit()
    login(client, user, company)
    path = f"/oneri-sikayet/oneri/{suggestion.id}/degerlendir"
    client.post(path, data={f"rating_{p.id}": "2" for p in parameters[:2]})
    client.post(path, data={f"rating_{parameters[0].id}": "", f"rating_{parameters[1].id}": "7",
                           f"rating_{parameters[2].id}": "11"})
    assert {row.parameter_id: row.rating for row in suggestion.evaluations} == {
        parameters[0].id: 2, parameters[1].id: 2}


def test_inactive_or_missing_criteria_do_not_falsely_complete_evaluation(client):
    company = create_company("CRITERIA")
    user = create_user("criteria-evaluator", company=company, permissions=("suggestions.evaluate",))
    active = SuggestionScoreParameter(company_id=company.id, name="Active", score=1, sort_order=1, is_active=True)
    inactive = SuggestionScoreParameter(company_id=company.id, name="Inactive", score=1, sort_order=2, is_active=False)
    suggestion = Suggestion(company_id=company.id, owner_name="Owner", definition="Criteria test",
                            status=SUGGESTION_IN_EVALUATION_STATUS)
    db.session.add_all([active, inactive, suggestion])
    db.session.commit()
    login(client, user, company)
    path = f"/oneri-sikayet/oneri/{suggestion.id}"
    client.post(path + "/degerlendir", data={f"rating_{active.id}": "3"})
    assert suggestion.status == SUGGESTION_COMPLETED_STATUS
    active.is_active = False
    db.session.commit()
    client.get(path)
    assert suggestion.status == SUGGESTION_IN_EVALUATION_STATUS
    active.is_active = True
    suggestion.evaluations[0].rating = 0
    db.session.commit()
    client.get(path)
    assert suggestion.status == SUGGESTION_IN_EVALUATION_STATUS
    assert "Değerlendirme Bekliyor" in client.get(path).get_data(as_text=True)
