from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from collector import fetch_jobs
from store import Store


def create_app(database_path=None):
    app = Flask(__name__)
    path = database_path or os.environ.get("JOB_DASHBOARD_DB") or Path(__file__).parent / "data" / "jobs.db"
    app.store = Store(path)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/jobs")
    def jobs():
        return jsonify(app.store.list_jobs(request.args.to_dict()))

    @app.get("/api/jobs/<external_id>")
    def job_detail(external_id):
        job = app.store.get_job(external_id)
        return jsonify(job) if job else (jsonify({"error": "공고를 찾을 수 없습니다."}), 404)

    @app.get("/api/stats")
    def stats():
        return jsonify(app.store.stats())

    @app.post("/api/sync")
    def sync():
        payload = request.get_json(silent=True) or {}
        pages = max(1, min(int(payload.get("pages", 2)), 10))
        jobs = fetch_jobs(pages=pages)
        app.store.upsert_jobs(jobs)
        return jsonify({"collected": len(jobs), "pages": pages, "source": "JOB-ALIO"})

    @app.get("/api/applications")
    def applications():
        return jsonify(app.store.list_applications())

    @app.post("/api/applications")
    def save_application():
        payload = request.get_json(silent=True) or {}
        job_id, status = str(payload.get("job_id") or ""), str(payload.get("status") or "관심")
        if not app.store.get_job(job_id):
            return jsonify({"error": "공고를 찾을 수 없습니다."}), 404
        app.store.save_application(job_id, status, str(payload.get("notes") or ""), str(payload.get("next_action_date") or ""))
        return jsonify({"saved": True}), 201

    @app.delete("/api/applications/<job_id>")
    def delete_application(job_id):
        app.store.delete_application(job_id)
        return jsonify({"deleted": True})

    @app.get("/api/filters")
    def filters():
        return jsonify(app.store.list_filters())

    @app.post("/api/filters")
    def save_filter():
        payload = request.get_json(silent=True) or {}
        name, criteria = str(payload.get("name") or "").strip(), payload.get("criteria") or {}
        if not name:
            return jsonify({"error": "필터 이름이 필요합니다."}), 400
        filter_id = app.store.save_filter(name, criteria)
        return jsonify({"id": filter_id}), 201

    @app.delete("/api/filters/<int:filter_id>")
    def delete_filter(filter_id):
        app.store.delete_filter(filter_id)
        return jsonify({"deleted": True})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5070, debug=False)
