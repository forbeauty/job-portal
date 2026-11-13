from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(title="Job Portal API v2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ЗАМЕНИТЕ НА ВАШИ ДАННЫЕ ПОДКЛЮЧЕНИЯ К POSTGRESQL
DB_CONFIG = {
    "dbname": "job_portal",      # имя вашей базы
    "user": "postgres",          # пользователь
    "password": "123", # ВАШ ПАРОЛЬ ОТ POSTGRESQL
    "host": "localhost",
    "port": "5432"
}

def get_db():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)

# --- МОДЕЛИ ДАННЫХ ---
class UserRegister(BaseModel):
    email: str
    password: str
    role: str  # 'seeker' или 'employer'
    full_name: str
    phone: Optional[str] = ""
    company_name: Optional[str] = ""
    resume_title: Optional[str] = ""
    resume_skills: Optional[str] = ""

class UserLogin(BaseModel):
    email: str
    password: str

class ProfileUpdate(BaseModel):
    full_name: str
    phone: str
    company_name: Optional[str] = ""
    resume_title: Optional[str] = ""
    resume_skills: Optional[str] = ""

class VacancyCreate(BaseModel):
    title: str
    description: str
    salary: int
    city: str
    work_format: str
    category_id: int
    company_name: str
    employer_id: int

class ApplicationCreate(BaseModel):
    vacancy_id: int
    seeker_id: int
    cover_letter: Optional[str] = ""

class StatusUpdate(BaseModel):
    status: str  # 'Приглашен', 'Отказ', 'На рассмотрении'

# --- АВТОРИЗАЦИЯ И ПРОФИЛИ ---
@app.post("/api/register")
def register(user: UserRegister):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO users (email, password, role, full_name, phone, company_name, resume_title, resume_skills)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, email, role, full_name, phone, company_name, resume_title, resume_skills
        """, (user.email, user.password, user.role, user.full_name, user.phone,
              user.company_name, user.resume_title, user.resume_skills))
        new_user = cur.fetchone()
        conn.commit()
        return new_user
    except psycopg2.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")
    finally:
        cur.close()
        conn.close()

@app.post("/api/login")
def login(creds: UserLogin):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, email, role, full_name, phone, company_name, resume_title, resume_skills
        FROM users WHERE email = %s AND password = %s
    """, (creds.email, creds.password))
    user = cur.fetchone()
    cur.close()
    conn.close()
    if not user:
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    return user

@app.put("/api/users/{user_id}")
def update_profile(user_id: int, data: ProfileUpdate):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE users
        SET full_name = %s, phone = %s, company_name = %s, resume_title = %s, resume_skills = %s
        WHERE id = %s
        RETURNING id, email, role, full_name, phone, company_name, resume_title, resume_skills
    """, (data.full_name, data.phone, data.company_name, data.resume_title, data.resume_skills, user_id))
    updated = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return updated

# --- КАТЕГОРИИ И СТАТИСТИКА ---
@app.get("/api/categories")
def get_categories():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM categories ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

@app.get("/api/stats")
def get_stats():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS count FROM vacancies")
    vacancies = cur.fetchone()["count"]
    cur.execute("SELECT COUNT(*) AS count FROM companies")
    companies = cur.fetchone()["count"]
    cur.execute("SELECT COUNT(*) AS count FROM applications")
    applications = cur.fetchone()["count"]
    cur.close()
    conn.close()
    return {"vacancies": vacancies, "companies": companies, "applications": applications}

# --- ВАКАНСИИ ---
@app.get("/api/vacancies")
def get_vacancies(category_id: Optional[int] = None, search: Optional[str] = None,
                  min_salary: Optional[int] = None, work_format: Optional[str] = None):
    conn = get_db()
    cur = conn.cursor()
    query = """
        SELECT v.*, c.name AS company_name, cat.name AS category_name
        FROM vacancies v
        LEFT JOIN companies c ON v.company_id = c.id
        LEFT JOIN categories cat ON v.category_id = cat.id
        WHERE 1=1
    """
    params = []
    if category_id:
        query += " AND v.category_id = %s"
        params.append(category_id)
    if search:
        query += " AND (LOWER(v.title) LIKE %s OR LOWER(v.description) LIKE %s)"
        params.extend([f"%{search.lower()}%", f"%{search.lower()}%"])
    if min_salary:
        query += " AND v.salary >= %s"
        params.append(min_salary)
    if work_format:
        query += " AND v.work_format = %s"
        params.append(work_format)

    query += " ORDER BY v.id DESC"
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

@app.post("/api/vacancies")
def create_vacancy(vac: VacancyCreate):
    conn = get_db()
    cur = conn.cursor()
    # Проверяем роль пользователя
    cur.execute("SELECT role FROM users WHERE id = %s", (vac.employer_id,))
    user = cur.fetchone()
    if not user or user["role"] != "employer":
        cur.close()
        conn.close()
        raise HTTPException(status_code=403, detail="Только работодатели могут публиковать вакансии")

    # Находим или создаем компанию
    cur.execute("SELECT id FROM companies WHERE LOWER(name) = LOWER(%s)", (vac.company_name,))
    comp = cur.fetchone()
    if comp:
        company_id = comp["id"]
    else:
        cur.execute("INSERT INTO companies (name, city) VALUES (%s, %s) RETURNING id", (vac.company_name, vac.city))
        company_id = cur.fetchone()["id"]

    cur.execute("""
        INSERT INTO vacancies (title, description, salary, city, work_format, category_id, company_id, employer_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (vac.title, vac.description, vac.salary, vac.city, vac.work_format, vac.category_id, company_id, vac.employer_id))
    new_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return {"id": new_id, "message": "Вакансия успешно опубликована"}

@app.delete("/api/vacancies/{vacancy_id}")
def delete_vacancy(vacancy_id: int, employer_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM vacancies WHERE id = %s AND (employer_id = %s OR employer_id IS NULL)", (vacancy_id, employer_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Вакансия удалена"}

# --- ОТКЛИКИ НА ВАКАНСИИ ---
@app.post("/api/applications")
def apply_vacancy(app_data: ApplicationCreate):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT role FROM users WHERE id = %s", (app_data.seeker_id,))
    user = cur.fetchone()
    if not user or user["role"] != "seeker":
        cur.close()
        conn.close()
        raise HTTPException(status_code=403, detail="Откликаться могут только соискатели")
    try:
        cur.execute("""
            INSERT INTO applications (vacancy_id, seeker_id, cover_letter)
            VALUES (%s, %s, %s) RETURNING id
        """, (app_data.vacancy_id, app_data.seeker_id, app_data.cover_letter))
        conn.commit()
        return {"message": "Отклик с данными вашего резюме отправлен!"}
    except psycopg2.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Вы уже откликались на эту вакансию")
    finally:
        cur.close()
        conn.close()

@app.get("/api/seekers/{seeker_id}/applications")
def get_seeker_applications(seeker_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.id, a.status, a.cover_letter, a.created_at,
               v.title AS vacancy_title, v.salary, v.city, c.name AS company_name
        FROM applications a
        JOIN vacancies v ON a.vacancy_id = v.id
        LEFT JOIN companies c ON v.company_id = c.id
        WHERE a.seeker_id = %s
        ORDER BY a.created_at DESC
    """, (seeker_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

@app.get("/api/employers/{employer_id}/applications")
def get_employer_applications(employer_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.id, a.status, a.cover_letter, a.created_at,
               v.title AS vacancy_title,
               u.full_name, u.email, u.phone, u.resume_title, u.resume_skills
        FROM applications a
        JOIN vacancies v ON a.vacancy_id = v.id
        JOIN users u ON a.seeker_id = u.id
        WHERE v.employer_id = %s OR v.employer_id IS NULL
        ORDER BY a.created_at DESC
    """, (employer_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

@app.patch("/api/applications/{app_id}/status")
def update_application_status(app_id: int, data: StatusUpdate):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE applications SET status = %s WHERE id = %s", (data.status, app_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Статус обновлен"}