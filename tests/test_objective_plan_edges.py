import pytest

from app.extensions import db
from app.models import Action
from tests.test_objective_plans import (
    business_snapshot, create_plan, plan_path, plan_scenario, set_permissions,
)


@pytest.mark.parametrize('kind', ['project', 'action'])
def test_manage_permission_retains_existing_implicit_source_read(client, plan_scenario, kind):
    s = plan_scenario
    permissions = ['quality_objective.manage', 'projects.view', 'projects.create',
                   'actions.create', 'actions.view_all']
    set_permissions(s.manager, permissions)
    assert client.get(plan_path(s, kind)).status_code == 200
    assert create_plan(client, s, kind).created_by_user_id == s.manager.id


@pytest.mark.parametrize('archived', [False, True])
def test_linked_action_delete_preserves_data_and_evidence(client, plan_scenario, monkeypatch, archived):
    s = plan_scenario
    link = create_plan(client, s, 'action')
    action = db.session.get(Action, link.action_id)
    action.file_stored_name = 'protected-plan-evidence.xlsx'
    if archived:
        s.objective.status = 'Arşiv'
    db.session.commit()
    before = business_snapshot(s)
    cleanup = []
    monkeypatch.setattr('app.routes.delete_stored_upload', lambda path: cleanup.append(path))
    for method in (client.get, client.post):
        assert method(f'/actions/{action.id}/delete').status_code == 409
        assert business_snapshot(s) == before
    assert not cleanup
    assert db.session.get(Action, action.id).file_stored_name == 'protected-plan-evidence.xlsx'
