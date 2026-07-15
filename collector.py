from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urljoin, urlparse, parse_qs, urlunparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://job.alio.go.kr"
LIST_URL = f"{BASE_URL}/recruit.do"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PublicJobDashboard/1.0; public-data research)"}


def clean(value: str) -> str:
    return " ".join((value or "").split())


def normalize_date(value: str) -> str:
    value = clean(value).replace(".", "-")
    if re.fullmatch(r"\d{2}-\d{2}-\d{2}", value):
        return f"20{value}"
    return value


def parse_job_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for link in soup.select('a[href*="recruitview.do?idx="]'):
        row = link.find_parent("tr")
        title_cell = link.find_parent("td")
        cells = row.find_all("td", recursive=False) if row else []
        if not title_cell or title_cell not in cells:
            continue
        title_index = cells.index(title_cell)
        if len(cells) <= title_index + 6:
            continue
        href = link.get("href", "")
        external_id = parse_qs(urlparse(href).query).get("idx", [""])[0]
        if not external_id:
            continue
        close_text = clean(cells[title_index + 5].get_text(" ", strip=True))
        close_match = re.search(r"\d{2,4}[.-]\d{2}[.-]\d{2}", close_text)
        d_day_match = re.search(r"D(?:-|\+)\d+|D-DAY", close_text, re.IGNORECASE)
        jobs.append({
            "external_id": external_id,
            "title": clean(title_cell.get_text(" ", strip=True)),
            "organization": clean(cells[title_index + 1].get_text(" ", strip=True)),
            "location": clean(cells[title_index + 2].get_text(" ", strip=True)),
            "employment_type": clean(cells[title_index + 3].get_text(" ", strip=True)),
            "posted_date": normalize_date(cells[title_index + 4].get_text(" ", strip=True)),
            "close_date": normalize_date(close_match.group() if close_match else close_text),
            "d_day": d_day_match.group() if d_day_match else "",
            "source_status": clean(cells[title_index + 6].get_text(" ", strip=True)),
            "source_url": urljoin(BASE_URL, href),
        })
    return jobs


def _field_map(table) -> dict[str, tuple[str, object]]:
    fields = {}
    for row in table.select("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        for index in range(0, len(cells) - 1, 2):
            label = clean(cells[index].get_text(" ", strip=True))
            cell = cells[index + 1]
            fields[label] = (clean(cell.get_text(" ", strip=True)), cell)
    return fields


def parse_job_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.select("table")
    fields = _field_map(tables[0]) if tables else {}

    def value(name: str) -> str:
        return fields.get(name, ("", None))[0]

    period = re.findall(r"\d{2,4}[.-]\d{2}[.-]\d{2}", value("채용기간"))
    salary_cell = fields.get("급여정보", ("", None))[1]
    salary_link = salary_cell.select_one("a[href]") if salary_cell else None
    headcount_match = re.search(r"\d+", value("채용인원"))
    process_steps = []
    attachments = []
    for table in tables[1:]:
        text = clean(table.get_text(" ", strip=True))
        if "결과 확정일" in text and "구분" in text:
            for row in table.select("tr")[1:]:
                cells = [clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
                if cells and cells[0] != "구분":
                    process_steps.append({"name": cells[0], "headcount": cells[1] if len(cells) > 1 else "-", "result_date": cells[3] if len(cells) > 3 else "-"})
        if "공고문" in text or "직무기술서" in text:
            for link in table.select("a[href]"):
                attachments.append({"name": clean(link.get_text(" ", strip=True)), "url": urljoin(BASE_URL, link.get("href", ""))})
    process_steps = list({(item["name"], item["headcount"], item["result_date"]): item for item in process_steps}.values())
    attachments = list({(item["name"], item["url"]): item for item in attachments}.values())
    apply_url = ""
    for link in soup.select("a[href^='http']"):
        href = link.get("href", "")
        if not any(domain in urlparse(href).netloc for domain in ("alio.go.kr", "job.alio.go.kr")):
            apply_url = href
            break
    return {
        "ncs": value("표준직무(NCS)"),
        "education": value("학력정보"),
        "work_field": value("근무분야"),
        "hire_type": value("채용구분"),
        "replacement": value("대체인력여부"),
        "location": value("근무지"),
        "employment_type": value("고용형태"),
        "headcount": int(headcount_match.group()) if headcount_match else None,
        "preferred": value("우대조건"),
        "period_start": normalize_date(period[0]) if period else "",
        "period_end": normalize_date(period[1]) if len(period) > 1 else "",
        "salary_reference_url": salary_link.get("href", "") if salary_link else "",
        "monthly_fixed_pay": None,
        "salary_note": "직무별 고정급은 공고·보수규정 원문 확인 필요",
        "process_steps": process_steps,
        "attachments": attachments,
        "apply_url": apply_url,
    }


def parse_alio_salary(html: str) -> dict:
    """Extract latest settlement-year standard new-hire fixed pay; ALIO table values are KRW thousands."""
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.select("table"):
        matrix = [[clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])] for row in table.select("tr")]
        labels = {row[0] for row in matrix if row}
        if not {"기본급", "고정수당", "합계"}.issubset(labels) or not matrix:
            continue
        settlement_columns = []
        for index, header in enumerate(matrix[0]):
            match = re.match(r"(\d{4})년 결산", header)
            if match:
                settlement_columns.append((index, int(match.group(1))))
        if not settlement_columns:
            continue
        column, year = max(settlement_columns, key=lambda item: item[1])
        values = {row[0]: row[column] for row in matrix[1:] if len(row) > column}
        try:
            base = int(values["기본급"].replace(",", "")) * 1000
            fixed = int(values["고정수당"].replace(",", "")) * 1000
        except (KeyError, ValueError):
            continue
        return {
            "salary_year": year,
            "annual_base_pay": base,
            "annual_fixed_allowance": fixed,
            "monthly_fixed_pay": (base + fixed) // 12,
            "salary_kind": "ALIO_STANDARD_NEW_HIRE",
            "salary_note": "ALIO 대졸 사무직 표준 신입 참고값 · 해당 직무 확정값 아님 · 성과급·실적수당 제외",
        }
    return {}


def fetch_alio_salary(reference_url: str, session: requests.Session, timeout: int = 25) -> dict:
    parsed = urlparse(reference_url)
    report_url = urlunparse(("https", "www.alio.go.kr", parsed.path, "", parsed.query, ""))
    response = session.get(report_url, headers={"Referer": "https://job.alio.go.kr/"}, timeout=timeout)
    response.raise_for_status()
    match = re.search(r'\.load\("([^\"]+/doc\.html)"', response.text)
    if not match:
        return {}
    document = session.get(urljoin(report_url, match.group(1)), timeout=timeout)
    document.raise_for_status()
    return parse_alio_salary(document.text)


def fetch_jobs(pages: int = 2, timeout: int = 25) -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)
    jobs = []
    for page in range(1, max(1, min(pages, 10)) + 1):
        response = session.get(LIST_URL, params={"pageNo": page}, timeout=timeout)
        response.raise_for_status()
        jobs.extend(parse_job_list(response.text))
    deduped = {job["external_id"]: job for job in jobs}

    def load_detail(job: dict) -> dict:
        response = session.get(job["source_url"], timeout=timeout)
        response.raise_for_status()
        detail = parse_job_detail(response.text)
        salary = {}
        if detail.get("salary_reference_url"):
            try:
                salary = fetch_alio_salary(detail["salary_reference_url"], session, timeout)
            except requests.RequestException:
                pass
        return {**job, **detail, **salary, "collected_at": datetime.now().isoformat(timespec="seconds")}

    results = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(load_detail, job): job for job in deduped.values()}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except requests.RequestException:
                results.append({**futures[future], "salary_note": "상세 공고 수집 실패 — 원문 확인 필요"})
    return results
