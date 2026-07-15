from app import create_app


def sample_job():
    return {
        "external_id": "302764", "title": "전산직 신입 채용", "organization": "서울물재생시설공단",
        "location": "서울", "employment_type": "정규직", "posted_date": "2026-07-15", "close_date": "2026-07-29",
        "d_day": "D-13", "source_status": "진행중", "source_url": "https://job.alio.go.kr/recruitview.do?idx=302764",
        "ncs": "정보통신", "education": "학력무관", "work_field": "전산직", "hire_type": "신입",
        "headcount": 2, "period_start": "2026-07-15", "period_end": "2026-07-29",
        "salary_note": "직무별 고정급은 공고·보수규정 원문 확인 필요", "monthly_fixed_pay": None,
        "process_steps": [{"name": "서류", "headcount": "10명", "result_date": "2026-08-01"}], "attachments": [],
    }


def test_api_lists_jobs_and_manages_application(tmp_path):
    app = create_app(tmp_path / "jobs.db")
    app.store.upsert_job(sample_job())
    client = app.test_client()

    jobs = client.get("/api/jobs?q=전산&location=서울").get_json()
    assert jobs[0]["headcount"] == 2
    assert jobs[0]["salary_note"].startswith("직무별")

    response = client.post("/api/applications", json={"job_id": "302764", "status": "서류준비", "notes": "자소서 작성", "next_action_date": "2026-07-25"})
    assert response.status_code == 201
    applications = client.get("/api/applications").get_json()
    assert applications[0]["organization"] == "서울물재생시설공단"
    assert applications[0]["application_status"] == "서류준비"


def test_api_saves_filter_and_syncs_collector_results(tmp_path, monkeypatch):
    app = create_app(tmp_path / "jobs.db")
    monkeypatch.setattr("app.fetch_jobs", lambda pages=2: [sample_job()])
    client = app.test_client()

    sync = client.post("/api/sync", json={"pages": 1})
    assert sync.status_code == 200
    assert sync.get_json()["collected"] == 1

    saved = client.post("/api/filters", json={"name": "서울 전산 신입", "criteria": {"q": "전산", "location": "서울", "hire_type": "신입"}})
    assert saved.status_code == 201
    assert client.get("/api/filters").get_json()[0]["criteria"]["hire_type"] == "신입"


def test_index_explains_single_screen_value_and_salary_limitations(tmp_path):
    app = create_app(tmp_path / "jobs.db")
    page = app.test_client().get("/").get_data(as_text=True)

    assert "공공채용 OS" in page
    assert "직무별 채용 인원" in page
    assert "성과급 제외" in page
    assert "내 지원현황" in page
    assert "저장 필터" in page
