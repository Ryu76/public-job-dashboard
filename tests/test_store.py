from store import Store


def job(external_id="1", title="전산직 채용", organization="서울물재생시설공단"):
    return {
        "external_id": external_id, "title": title, "organization": organization,
        "location": "서울", "employment_type": "정규직", "hire_type": "신입",
        "work_field": "전산직", "ncs": "정보통신", "headcount": 2,
        "posted_date": "2026-07-01", "close_date": "2026-07-31", "source_status": "진행중",
        "source_url": f"https://job.alio.go.kr/recruitview.do?idx={external_id}",
        "salary_note": "직무별 고정급은 공고·보수규정 원문 확인 필요",
    }


def test_store_filters_jobs_and_tracks_application(tmp_path):
    store = Store(tmp_path / "jobs.db")
    store.upsert_job(job())
    salary_job = job()
    salary_job.update({"salary_year": 2025, "annual_base_pay": 30_000_000, "annual_fixed_allowance": 6_000_000, "monthly_fixed_pay": 3_000_000, "salary_kind": "ALIO_STANDARD_NEW_HIRE"})
    store.upsert_job(salary_job)
    saved_salary = store.get_job("1")
    assert saved_salary["salary_year"] == 2025
    assert saved_salary["annual_base_pay"] == 30_000_000
    assert saved_salary["salary_kind"] == "ALIO_STANDARD_NEW_HIRE"
    admin_job = job("2", "행정직 채용", "다른기관")
    admin_job["work_field"] = "행정직"
    admin_job["ncs"] = "경영·회계·사무"
    store.upsert_job(admin_job)

    results = store.list_jobs({"q": "전산", "location": "서울", "hire_type": "신입"})
    assert [item["external_id"] for item in results] == ["1"]

    store.save_application("1", "서류제출", "자소서 제출 완료", "2026-08-10")
    applied = store.list_applications()
    assert applied[0]["application_status"] == "서류제출"
    assert applied[0]["notes"] == "자소서 제출 완료"


def test_store_saves_reusable_filter(tmp_path):
    store = Store(tmp_path / "jobs.db")
    filter_id = store.save_filter("서울 전산 신입", {"q": "전산", "location": "서울", "hire_type": "신입"})

    saved = store.list_filters()
    assert saved == [{"id": filter_id, "name": "서울 전산 신입", "criteria": {"q": "전산", "location": "서울", "hire_type": "신입"}}]


def test_store_supports_multiple_values_per_filter_and_education_categories(tmp_path):
    store = Store(tmp_path / "jobs.db")
    bachelor = job("1", "전산직 학사 채용")
    bachelor["education"] = "대졸(2~3년),대졸(4년),석사"
    admin = job("2", "행정직 고졸 채용")
    admin.update({"work_field": "행정직", "location": "경기", "hire_type": "경력", "education": "고졸"})
    doctor = job("3", "연구직 박사 채용")
    doctor.update({"work_field": "연구직", "location": "대전", "hire_type": "경력", "education": "박사"})
    store.upsert_jobs([bachelor, admin, doctor])

    results = store.list_jobs({
        "work_field": ["전산직", "행정직"],
        "location": ["서울", "경기"],
        "hire_type": ["신입", "경력"],
        "education": ["학사", "고졸"],
    })

    assert {item["external_id"] for item in results} == {"1", "2"}
    assert {item["external_id"] for item in store.list_jobs({"education": ["전문학사"]})} == {"1"}
    assert store.list_jobs({"education": ["무관"]}) == []
