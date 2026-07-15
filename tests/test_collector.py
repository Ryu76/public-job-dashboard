from pathlib import Path

from collector import parse_alio_salary, parse_job_detail, parse_job_list

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_job_list_extracts_real_job_alio_fields():
    jobs = parse_job_list((FIXTURES / "job_list.html").read_text(encoding="utf-8"))

    assert jobs == [{
        "external_id": "302764",
        "title": "한국기술교육대학교 HRD학과 겸임교수 채용 공고",
        "organization": "한국기술교육대학교",
        "location": "충남",
        "employment_type": "비정규직",
        "posted_date": "2026-07-15",
        "close_date": "2026-07-29",
        "d_day": "D-13",
        "source_status": "진행중",
        "source_url": "https://job.alio.go.kr/recruitview.do?idx=302764",
    }]


def test_parse_job_detail_extracts_headcount_process_salary_evidence_and_files():
    detail = parse_job_detail((FIXTURES / "job_detail.html").read_text(encoding="utf-8"))

    assert detail["ncs"] == "교육.자연.사회과학"
    assert detail["work_field"] == "교수직"
    assert detail["hire_type"] == "경력"
    assert detail["headcount"] == 1
    assert detail["period_start"] == "2026-07-15"
    assert detail["period_end"] == "2026-07-29"
    assert detail["salary_reference_url"] == "https://alio.go.kr/pay"
    assert detail["monthly_fixed_pay"] is None
    assert detail["salary_note"] == "직무별 고정급은 공고·보수규정 원문 확인 필요"
    assert [step["name"] for step in detail["process_steps"]] == ["1차", "최종"]
    assert detail["attachments"][0]["name"] == "공고문.hwp"


def test_parse_alio_salary_uses_latest_settlement_and_excludes_variable_pay():
    salary = parse_alio_salary((FIXTURES / "alio_salary.html").read_text(encoding="utf-8"))

    assert salary["salary_year"] == 2025
    assert salary["annual_base_pay"] == 22_524_000
    assert salary["annual_fixed_allowance"] == 7_727_000
    assert salary["monthly_fixed_pay"] == 2_520_916
    assert salary["salary_kind"] == "ALIO_STANDARD_NEW_HIRE"
    assert "직무 확정값 아님" in salary["salary_note"]
