from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db_connection():
    return psycopg2.connect(
        host="localhost",
        database="postgres",
        user="postgres",
        password="123",  # Укажите ваш фактический пароль
        port="5432",
        cursor_factory=RealDictCursor
    )

# --- СТАТИСТИКА И ДАННЫЕ ДЛЯ СОИСКАТЕЛЕЙ ---

@app.get("/api/stats")
def get_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM vacancies WHERE is_active = TRUE")
    v_count = cursor.fetchone()['count']
    cursor.execute("SELECT COUNT(*) FROM companies")
    c_count = cursor.fetchone()['count']
    cursor.execute("SELECT COUNT(*) FROM resumes")
    r_count = cursor.fetchone()['count']
    cursor.close()
    conn.close()
    return {"vacancies": v_count, "companies": c_count, "resumes": r_count}

@app.get("/api/categories")
def get_categories():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id, c.name, COUNT(v.id) as vacancy_count
        FROM categories c
        LEFT JOIN vacancies v ON c.id = v.category_id AND v.is_active = TRUE
        GROUP BY c.id, c.name ORDER BY vacancy_count DESC
    """)
    res = cursor.fetchall()
    cursor.close()
    conn.close()
    return res

# Получение вакансий с поддержкой фильтрации по категории
@app.get("/api/vacancies")
def get_vacancies(category_id: Optional[int] = Query(None)):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if category_id:
        cursor.execute("""
            SELECT v.id, v.title, v.description, v.salary_from, v.salary_to, c.name as company_name 
            FROM vacancies v
            LEFT JOIN companies c ON v.company_id = c.id
            WHERE v.is_active = TRUE AND v.category_id = %s
            ORDER BY v.id DESC
        """, (category_id,))
    else:
        cursor.execute("""
            SELECT v.id, v.title, v.description, v.salary_from, v.salary_to, c.name as company_name 
            FROM vacancies v
            LEFT JOIN companies c ON v.company_id = c.id
            WHERE v.is_active = TRUE 
            ORDER BY v.id DESC
        """)
        
    res = cursor.fetchall()
    cursor.close()
    conn.close()
    return res

# --- ДАННЫЕ ДЛЯ РАБОТОДАТЕЛЕЙ ---

@app.get("/api/resumes")
def get_resumes():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM resumes ORDER BY id DESC")
    res = cursor.fetchall()
    cursor.close()
    conn.close()
    return res

class VacancyCreate(BaseModel):
    title: str
    description: str
    salary_from: int
    category_id: int

@app.post("/api/vacancies")
def create_vacancy(v: VacancyCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO vacancies (title, description, salary_from, company_id, category_id) VALUES (%s, %s, %s, 1, %s)",
        (v.title, v.description, v.salary_from, v.category_id)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"status": "success"}

@app.delete("/api/vacancies/{vacancy_id}")
def delete_vacancy(vacancy_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM vacancies WHERE id = %s", (vacancy_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return {"status": "deleted"}
