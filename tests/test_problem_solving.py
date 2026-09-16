from datetime import date, timedelta
from io import BytesIO

from app.extensions import db
from app.models import AppSetting, AuditLog, Notification, ProblemSolvingCase, ProblemSolvingFile, ProblemSolvingStep
from app.problem_solving import STEP_TEMPLATES
from app.seed import ensure_runtime_schema
from .helpers import create_company, create_user, login

ALL_PERMISSIONS=("problem_solving.view","problem_solving.view_all","problem_solving.create","problem_solving.manage","problem_solving.update","problem_solving.review","problem_solving.archive","problem_solving.file_download")


def payload(leader,reviewer,method="A3",team=(),**overrides):
    values={"method":method,"title":"Kaynak Hatası Tekrarı","department":"Üretim","leader_user_id":str(leader.id),"reviewer_user_id":str(reviewer.id),"team_user_ids":[str(u.id) for u in team],"priority":"Yüksek","opened_date":date.today().isoformat(),"target_date":(date.today()+timedelta(days=30)).isoformat(),"problem_statement":"Kaynak hatası son üç partide tekrarlandı.","impact":"Yeniden işleme ve sevkiyat gecikmesi."}
    values.update(overrides); return values


def test_a3_full_gated_workflow_tasks_files_archive_and_isolation(app,client):
    company=create_company("721"); other=create_company("722")
    manager=create_user("ps-manager",company=company,permissions=ALL_PERMISSIONS)
    leader=create_user("ps-leader",company=company,permissions=("problem_solving.view","problem_solving.update","problem_solving.file_download"))
    reviewer=create_user("ps-reviewer",company=company,permissions=("problem_solving.view","problem_solving.review"))
    member=create_user("ps-member",company=company,permissions=("problem_solving.view","problem_solving.update"))
    outsider=create_user("ps-outsider",company=company,permissions=("problem_solving.view",))
    foreign=create_user("ps-foreign",company=other,permissions=ALL_PERMISSIONS)
    login(client,manager)
    response=client.post("/problem-cozme/yeni",data=payload(leader,reviewer,team=(member,),attachment=(BytesIO(b"problem"),"baslangic.pdf")),content_type="multipart/form-data",follow_redirects=True)
    assert response.status_code==200 and "A3-2026-0001" in response.get_data(as_text=True)
    case=ProblemSolvingCase.query.one(); assert len(case.steps)==len(STEP_TEMPLATES["A3"])==7
    assert case.steps[0].status=="Devam Ediyor" and case.steps[1].status=="Bekliyor"
    assert {m.user_id for m in case.team_members}=={leader.id,member.id}
    assert ProblemSolvingFile.query.one().sha256_hash
    login(client,outsider); assert client.get(f"/problem-cozme/{case.id}").status_code==404
    login(client,foreign); assert client.get(f"/problem-cozme/{case.id}").status_code==404
    login(client,member); assert case.case_no in client.get("/uzerime-atananlar?module=problem_solving").get_data(as_text=True)

    # İlk aşama bir kez iade edilir; sonraki aşama onay olmadan açılamaz.
    assert client.post(f"/problem-cozme/{case.id}/asama",data={"content":"İlk analiz ve veri özeti."}).status_code==302
    db.session.refresh(case); assert case.current_step==1 and case.steps[0].status=="İnceleme Bekliyor"
    login(client,reviewer); client.post(f"/problem-cozme/{case.id}/incele",data={"decision":"return","review_note":"Ölçüm verisini ekleyin."})
    db.session.refresh(case); assert case.current_step==1 and case.steps[0].status=="Revizyon Bekliyor"
    login(client,leader); client.post(f"/problem-cozme/{case.id}/asama",data={"content":"Ölçüm verisi eklenmiş analiz."})
    login(client,reviewer); client.post(f"/problem-cozme/{case.id}/incele",data={"decision":"approve","review_note":"Uygun."})
    db.session.refresh(case); assert case.current_step==2 and case.steps[0].status=="Onaylandı"

    for expected_step in range(2,len(case.steps)+1):
        login(client,leader); client.post(f"/problem-cozme/{case.id}/asama",data={"content":f"{expected_step}. aşama çalışması ve kanıtı."})
        login(client,reviewer); client.post(f"/problem-cozme/{case.id}/incele",data={"decision":"approve","review_note":"Doğrulandı."})
        db.session.refresh(case)
    assert case.status=="Tamamlandı" and case.completed_at is not None
    login(client,manager); assert client.post(f"/problem-cozme/{case.id}/arsivle").status_code==302
    db.session.refresh(case); assert case.status=="Arşiv" and case.archived_at is not None
    assert AuditLog.query.filter_by(entity_type="ProblemSolvingCase").count()>=1
    assert AuditLog.query.filter_by(entity_type="ProblemSolvingStep").count()>=1
    assert Notification.query.filter(Notification.source_key.like(f"problem-solving:review-%:{case.id}:{reviewer.id}")).count()>=1


def test_8d_steps_sequence_validation_and_invalid_file(client):
    company=create_company("723"); manager=create_user("ps-validation",company=company,permissions=ALL_PERMISSIONS); reviewer=create_user("ps-validation-review",company=company,permissions=ALL_PERMISSIONS)
    login(client,manager)
    assert client.post("/problem-cozme/yeni",data=payload(manager,manager),follow_redirects=True).status_code==200
    assert ProblemSolvingCase.query.count()==0
    assert client.post("/problem-cozme/yeni",data=payload(manager,reviewer,method="8D")).status_code==302
    case=ProblemSolvingCase.query.one(); assert case.case_no=="8D-2026-0001" and len(case.steps)==8
    bad=client.post("/problem-cozme/yeni",data=payload(manager,reviewer,title="İkinci",attachment=(BytesIO(b"x"),"zararli.exe")),content_type="multipart/form-data",follow_redirects=True)
    assert bad.status_code==200 and ProblemSolvingCase.query.count()==1


def test_runtime_schema_marks_problem_solving_done(app):
    AppSetting.query.filter_by(key="sales_readiness:competitor_a3_problem_solving").delete(); db.session.commit(); ensure_runtime_schema()
    setting=db.session.get(AppSetting,"sales_readiness:competitor_a3_problem_solving"); assert setting and setting.value=="1"
