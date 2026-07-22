from pathlib import Path

from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from alembic import command
from app.core.auth import hash_password
from app.core.database import create_database_engine
from app.main import create_app
from app.models.user import User


def migrate_database(settings, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    command.upgrade(Config(str(Path(__file__).parents[2] / "alembic.ini")), "head")


def test_register_login_remember_and_logout(settings, monkeypatch) -> None:
    migrate_database(settings, monkeypatch)
    with TestClient(create_app(settings)) as client:
        register_response = client.post(
            "/api/auth/register",
            json={"username": "student-a", "password": "secret6", "fullName": "学生甲"},
        )
        assert register_response.status_code == 201
        assert register_response.json()["role"] == "STUDENT"

        duplicate_response = client.post(
            "/api/auth/register",
            json={"username": "student-a", "password": "secret6", "fullName": "学生甲"},
        )
        assert duplicate_response.status_code == 409

        login_response = client.post(
            "/api/auth/login",
            json={"username": "student-a", "password": "secret6", "rememberLogin": True},
        )
        assert login_response.status_code == 200
        token = login_response.json()["token"]
        assert login_response.json()["user"]["fullName"] == "学生甲"
        me_response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_response.status_code == 200

        logout_response = client.post(
            "/api/auth/logout", headers={"Authorization": f"Bearer {token}"}
        )
        assert logout_response.status_code == 204
        expired_response = client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert expired_response.status_code == 401


def test_student_cannot_manage_questions(settings, monkeypatch) -> None:
    migrate_database(settings, monkeypatch)
    with TestClient(create_app(settings)) as client:
        register_response = client.post(
            "/api/auth/register",
            json={"username": "student-b", "password": "secret6", "fullName": "学生乙"},
        )
        token = client.post(
            "/api/auth/login",
            json={"username": "student-b", "password": "secret6"},
        ).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        question = {
            "questionContent": "题目",
            "standardAnswer": "答案",
            "rubricPoints": ["评分点"],
            "commonErrors": ["错误"],
            "alternativeSolutions": ["其他解法"],
            "layeredHints": ["提示"],
            "guidedQuestions": [],
            "fullSolution": "解析",
        }
        assert register_response.status_code == 201
        assert client.post("/api/questions", json=question, headers=headers).status_code == 403


def test_session_api_requires_login(settings, monkeypatch) -> None:
    migrate_database(settings, monkeypatch)
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/sessions", json={"questionId": 1})
        assert response.status_code == 401
        assert response.json()["detail"] == "请先登录"


def test_teacher_account_can_be_added_manually(settings, monkeypatch) -> None:
    migrate_database(settings, monkeypatch)
    engine = create_database_engine(settings)
    try:
        with Session(engine) as session:
            session.add(
                User(
                    username="teacher-a",
                    password_hash=hash_password("secret6"),
                    full_name="教师甲",
                    role="TEACHER",
                )
            )
            session.commit()
        with TestClient(create_app(settings)) as client:
            response = client.post(
                "/api/auth/login",
                json={"username": "teacher-a", "password": "secret6"},
            )
            assert response.status_code == 200
            token = response.json()["token"]
            assert response.json()["user"]["role"] == "TEACHER"
            questions_response = client.get(
                "/api/questions", headers={"Authorization": f"Bearer {token}"}
            )
            assert questions_response.status_code == 200
    finally:
        engine.dispose()
