from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path
from app.config import settings
from app.database import create_tables
from app.seed import seed_database
from app.routers import auth, ai, superadmin, invitations, chat, teacher, student, parent, corporate
from app.routers import notifications, messages, timetable
from app.routers import content, repetitor
from app.routers import websocket as ws_router
from app.routers import courses as courses_router

# Yükləmə qovluğu
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
(UPLOAD_DIR / "homework").mkdir(exist_ok=True)


async def _migrate_db():
    """Add new columns if they don't exist (SQLite idempotent migrations)."""
    from app.database import engine
    import sqlalchemy as sa

    async def _add_col(conn, table: str, col: str, col_def: str):
        """ALTER TABLE … ADD COLUMN, silently skips if already exists."""
        try:
            await conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))
            await conn.commit()
        except Exception:
            pass  # column already exists

    async with engine.connect() as conn:
        # exams: cədvəl avto-aktivləşmə + exam_results pozuntu sayı
        try:
            res = await conn.execute(sa.text("PRAGMA table_info(exams)"))
            exam_cols = {row[1] for row in res.fetchall()}
            if "auto_activated" not in exam_cols:
                await _add_col(conn, "exams", "auto_activated", "BOOLEAN DEFAULT 0")
            res2 = await conn.execute(sa.text("PRAGMA table_info(exam_results)"))
            er_cols = {row[1] for row in res2.fetchall()}
            if "violations" not in er_cols:
                await _add_col(conn, "exam_results", "violations", "INTEGER DEFAULT 0")
            if "manual_grades" not in er_cols:
                await _add_col(conn, "exam_results", "manual_grades", "TEXT")
        except Exception:
            pass

        # users columns
        result = await conn.execute(sa.text("PRAGMA table_info(users)"))
        user_cols = {row[1] for row in result.fetchall()}
        if "student_limit" not in user_cols:
            await conn.execute(sa.text("ALTER TABLE users ADD COLUMN student_limit INTEGER DEFAULT 0 NOT NULL"))
            await conn.commit()
        if "avatar_url" not in user_cols:
            await _add_col(conn, "users", "avatar_url", "TEXT")
        if "subjects_json" not in user_cols:
            await _add_col(conn, "users", "subjects_json", "TEXT")

        # tenants: subscription + AI limits + feature flags + branding
        result = await conn.execute(sa.text("PRAGMA table_info(tenants)"))
        tenant_cols = {row[1] for row in result.fetchall()}
        if "plan" not in tenant_cols:
            await _add_col(conn, "tenants", "plan", "VARCHAR(20) DEFAULT 'free'")
        if "plan_expires_at" not in tenant_cols:
            await _add_col(conn, "tenants", "plan_expires_at", "VARCHAR(30)")
        if "monthly_fee" not in tenant_cols:
            await _add_col(conn, "tenants", "monthly_fee", "INTEGER DEFAULT 0")
        if "ai_daily_limit" not in tenant_cols:
            await _add_col(conn, "tenants", "ai_daily_limit", "INTEGER DEFAULT 0")
        if "features" not in tenant_cols:
            await _add_col(conn, "tenants", "features", "VARCHAR(500) DEFAULT '{}'")
        if "logo_url" not in tenant_cols:
            await _add_col(conn, "tenants", "logo_url", "VARCHAR(500)")
        if "primary_color" not in tenant_cols:
            await _add_col(conn, "tenants", "primary_color", "VARCHAR(10)")

        # announcement_history: scheduled announcements
        result = await conn.execute(sa.text("PRAGMA table_info(announcement_history)"))
        ann_cols = {row[1] for row in result.fetchall()}
        if "scheduled_at" not in ann_cols:
            await _add_col(conn, "announcement_history", "scheduled_at", "VARCHAR(30)")
        if "is_sent" not in ann_cols:
            await _add_col(conn, "announcement_history", "is_sent", "INTEGER DEFAULT 1")

        # ── Indexes (CREATE INDEX IF NOT EXISTS — idempotent) ────────────────
        indexes = [
            # users — ən çox sorğulanan sütunlar
            "CREATE INDEX IF NOT EXISTS idx_users_tenant_id    ON users(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_users_role         ON users(role)",
            "CREATE INDEX IF NOT EXISTS idx_users_tenant_role  ON users(tenant_id, role)",
            "CREATE INDEX IF NOT EXISTS idx_users_tenant_active ON users(tenant_id, is_active)",
            "CREATE INDEX IF NOT EXISTS idx_users_email        ON users(email)",
            # students
            "CREATE INDEX IF NOT EXISTS idx_students_user_id   ON students(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_students_class_id  ON students(class_id)",
            # classes
            "CREATE INDEX IF NOT EXISTS idx_classes_tenant_id  ON classes(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_classes_teacher_id ON classes(teacher_id)",
            # exams
            "CREATE INDEX IF NOT EXISTS idx_exams_teacher_id   ON exams(teacher_id)",
            "CREATE INDEX IF NOT EXISTS idx_exams_class_id     ON exams(class_id)",
            # exam_results
            "CREATE INDEX IF NOT EXISTS idx_results_exam_id    ON exam_results(exam_id)",
            "CREATE INDEX IF NOT EXISTS idx_results_student_id ON exam_results(student_id)",
            # tenants
            "CREATE INDEX IF NOT EXISTS idx_tenants_slug       ON tenants(slug)",
            "CREATE INDEX IF NOT EXISTS idx_tenants_is_active  ON tenants(is_active)",
        ]
        for idx_sql in indexes:
            try:
                await conn.execute(sa.text(idx_sql))
                await conn.commit()
            except Exception:
                pass

        # ── repetitor_payments: qismi ödəniş + üsul ──────────────────────────
        try:
            res = await conn.execute(sa.text("PRAGMA table_info(repetitor_payments)"))
            pay_cols = {row[1] for row in res.fetchall()}
            if "paid_amount" not in pay_cols:
                await _add_col(conn, "repetitor_payments", "paid_amount", "INTEGER DEFAULT 0")
            if "method" not in pay_cols:
                await _add_col(conn, "repetitor_payments", "method", "VARCHAR(20)")
        except Exception:
            pass

        # ── homeworks: attachments sütunu ────────────────────────────────────
        result = await conn.execute(sa.text("PRAGMA table_info(homeworks)"))
        hw_cols = {row[1] for row in result.fetchall()}
        if "attachments" not in hw_cols:
            await _add_col(conn, "homeworks", "attachments", "TEXT DEFAULT '[]'")

        # ── Gamification: nişanlar + streak tracking ──────────────────────────
        result = await conn.execute(sa.text("PRAGMA table_info(students)"))
        stu_cols = {row[1] for row in result.fetchall()}
        if "earned_badges" not in stu_cols:
            await _add_col(conn, "students", "earned_badges", "TEXT DEFAULT '[]'")
        if "last_active_date" not in stu_cols:
            await _add_col(conn, "students", "last_active_date", "VARCHAR(10)")

        # ── Strukturlu kurslar ────────────────────────────────────────────────
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS courses (
                id VARCHAR PRIMARY KEY,
                teacher_id VARCHAR NOT NULL REFERENCES users(id),
                title VARCHAR(200) NOT NULL,
                subject VARCHAR(100) NOT NULL,
                description TEXT,
                is_published INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS course_modules (
                id VARCHAR PRIMARY KEY,
                course_id VARCHAR NOT NULL REFERENCES courses(id),
                title VARCHAR(200) NOT NULL,
                description VARCHAR(500),
                order_index INTEGER DEFAULT 0
            )
        """))
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS lessons (
                id VARCHAR PRIMARY KEY,
                module_id VARCHAR NOT NULL REFERENCES course_modules(id),
                title VARCHAR(200) NOT NULL,
                content TEXT,
                lesson_type VARCHAR(20) DEFAULT 'text',
                url VARCHAR(500),
                order_index INTEGER DEFAULT 0,
                duration_min INTEGER DEFAULT 5
            )
        """))
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS lesson_progress (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL REFERENCES users(id),
                lesson_id VARCHAR NOT NULL REFERENCES lessons(id),
                completed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, lesson_id)
            )
        """))
        # Course professional sütunları (idempotent)
        res_c = await conn.execute(sa.text("PRAGMA table_info(courses)"))
        course_cols = {row[1] for row in res_c.fetchall()}
        if "subtitle" not in course_cols:
            await _add_col(conn, "courses", "subtitle", "VARCHAR(300)")
        if "level" not in course_cols:
            await _add_col(conn, "courses", "level", "VARCHAR(20) DEFAULT 'beginner'")
        if "cover_color" not in course_cols:
            await _add_col(conn, "courses", "cover_color", "VARCHAR(20) DEFAULT '#2196F3'")
        if "objectives" not in course_cols:
            await _add_col(conn, "courses", "objectives", "TEXT DEFAULT '[]'")
        if "tags" not in course_cols:
            await _add_col(conn, "courses", "tags", "TEXT DEFAULT '[]'")
        if "prerequisite_id" not in course_cols:
            await _add_col(conn, "courses", "prerequisite_id", "VARCHAR")
        if "cover_image" not in course_cols:
            await _add_col(conn, "courses", "cover_image", "VARCHAR(500)")
        if "assignment_mode" not in course_cols:
            await _add_col(conn, "courses", "assignment_mode", "VARCHAR(20) DEFAULT 'public'")
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS course_assignments (
                id VARCHAR PRIMARY KEY,
                course_id VARCHAR NOT NULL REFERENCES courses(id),
                user_id VARCHAR NOT NULL REFERENCES users(id),
                UNIQUE(course_id, user_id)
            )
        """))
        await conn.commit()

        res_l = await conn.execute(sa.text("PRAGMA table_info(lessons)"))
        lesson_cols = {row[1] for row in res_l.fetchall()}
        if "file_name" not in lesson_cols:
            await _add_col(conn, "lessons", "file_name", "VARCHAR(300)")
        if "resources" not in lesson_cols:
            await _add_col(conn, "lessons", "resources", "TEXT DEFAULT '[]'")
        if "is_preview" not in lesson_cols:
            await _add_col(conn, "lessons", "is_preview", "BOOLEAN DEFAULT 0")

        # Kurs reytinqi + son baxılan dərs cədvəlləri
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS course_reviews (
                id VARCHAR PRIMARY KEY,
                course_id VARCHAR NOT NULL REFERENCES courses(id),
                user_id VARCHAR NOT NULL REFERENCES users(id),
                rating INTEGER DEFAULT 5,
                comment TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(course_id, user_id)
            )
        """))
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS course_last_viewed (
                id VARCHAR PRIMARY KEY,
                course_id VARCHAR NOT NULL REFERENCES courses(id),
                user_id VARCHAR NOT NULL REFERENCES users(id),
                lesson_id VARCHAR REFERENCES lessons(id),
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(course_id, user_id)
            )
        """))
        await conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_reviews_course ON course_reviews(course_id)"))

        # Modul quiz
        res_m = await conn.execute(sa.text("PRAGMA table_info(course_modules)"))
        mod_cols = {row[1] for row in res_m.fetchall()}
        if "quiz" not in mod_cols:
            await _add_col(conn, "course_modules", "quiz", "TEXT DEFAULT '[]'")
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS module_quiz_results (
                id VARCHAR PRIMARY KEY,
                module_id VARCHAR NOT NULL REFERENCES course_modules(id),
                user_id VARCHAR NOT NULL REFERENCES users(id),
                score INTEGER DEFAULT 0,
                passed INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_quiz_res_user ON module_quiz_results(user_id, module_id)"))

        # Dərs qeydləri + sual-cavab
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS lesson_notes (
                id VARCHAR PRIMARY KEY,
                lesson_id VARCHAR NOT NULL REFERENCES lessons(id),
                user_id VARCHAR NOT NULL REFERENCES users(id),
                content TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(lesson_id, user_id)
            )
        """))
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS lesson_comments (
                id VARCHAR PRIMARY KEY,
                lesson_id VARCHAR NOT NULL REFERENCES lessons(id),
                user_id VARCHAR NOT NULL REFERENCES users(id),
                parent_id VARCHAR,
                text TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_comments_lesson ON lesson_comments(lesson_id)"))
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS course_favorites (
                id VARCHAR PRIMARY KEY,
                course_id VARCHAR NOT NULL REFERENCES courses(id),
                user_id VARCHAR NOT NULL REFERENCES users(id),
                UNIQUE(course_id, user_id)
            )
        """))
        await conn.commit()

        await conn.execute(sa.text(
            "CREATE INDEX IF NOT EXISTS idx_courses_teacher ON courses(teacher_id)"
        ))
        await conn.execute(sa.text(
            "CREATE INDEX IF NOT EXISTS idx_lesson_prog_user ON lesson_progress(user_id)"
        ))
        await conn.commit()

        # ── Gündəlik tapşırıq cədvəli ─────────────────────────────────────────
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS daily_challenge_submissions (
                id VARCHAR PRIMARY KEY,
                student_id VARCHAR NOT NULL REFERENCES students(id),
                challenge_date VARCHAR(10) NOT NULL,
                question_id VARCHAR,
                is_correct INTEGER DEFAULT 0,
                xp_awarded INTEGER DEFAULT 0,
                submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(sa.text(
            "CREATE INDEX IF NOT EXISTS idx_daily_sub_stu_date ON daily_challenge_submissions(student_id, challenge_date)"
        ))
        await conn.commit()

        # ── Repetitor tables (CREATE TABLE IF NOT EXISTS — idempotent) ───────
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS repetitor_classes (
                id VARCHAR PRIMARY KEY,
                teacher_id VARCHAR NOT NULL REFERENCES users(id),
                name VARCHAR(100) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS repetitor_subjects (
                id VARCHAR PRIMARY KEY,
                teacher_id VARCHAR NOT NULL REFERENCES users(id),
                name VARCHAR(100) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS repetitor_students (
                id VARCHAR PRIMARY KEY,
                teacher_id VARCHAR NOT NULL REFERENCES users(id),
                name VARCHAR(150) NOT NULL,
                phone VARCHAR(30),
                email VARCHAR(255),
                subject VARCHAR(100) DEFAULT '',
                grade VARCHAR(20),
                hourly_rate INTEGER DEFAULT 0,
                notes TEXT,
                is_active INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS repetitor_sessions (
                id VARCHAR PRIMARY KEY,
                teacher_id VARCHAR NOT NULL REFERENCES users(id),
                student_id VARCHAR NOT NULL REFERENCES repetitor_students(id),
                subject VARCHAR(100) DEFAULT '',
                scheduled_at VARCHAR(30) NOT NULL,
                duration_min INTEGER DEFAULT 60,
                status VARCHAR(20) DEFAULT 'scheduled',
                score INTEGER,
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS repetitor_payments (
                id VARCHAR PRIMARY KEY,
                teacher_id VARCHAR NOT NULL REFERENCES users(id),
                student_id VARCHAR NOT NULL REFERENCES repetitor_students(id),
                amount INTEGER NOT NULL,
                month VARCHAR(7) NOT NULL,
                payment_date VARCHAR(10),
                status VARCHAR(10) DEFAULT 'unpaid',
                paid_at VARCHAR(30),
                note VARCHAR(300),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # Mövcud DB-ə payment_date sütununu əlavə et (artıq varsa keç)
        try:
            await conn.execute(sa.text(
                "ALTER TABLE repetitor_payments ADD COLUMN payment_date VARCHAR(10)"
            ))
        except Exception:
            pass
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS repetitor_daily_grades (
                id VARCHAR PRIMARY KEY,
                teacher_id VARCHAR NOT NULL REFERENCES users(id),
                student_id VARCHAR NOT NULL REFERENCES repetitor_students(id),
                subject VARCHAR(100) NOT NULL DEFAULT '',
                grade INTEGER NOT NULL,
                date VARCHAR(10) NOT NULL,
                note VARCHAR(300),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # ── Repetitor meetings ────────────────────────────────────────────────
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS repetitor_meetings (
                id VARCHAR PRIMARY KEY,
                teacher_id VARCHAR NOT NULL REFERENCES users(id),
                student_id VARCHAR NOT NULL REFERENCES repetitor_students(id),
                title VARCHAR(200) NOT NULL,
                meeting_date VARCHAR(30) NOT NULL,
                duration_min INTEGER DEFAULT 30,
                location VARCHAR(200),
                note TEXT,
                status VARCHAR(20) DEFAULT 'planned',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # ── Repetitor questions ────────────────────────────────────────────────
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS repetitor_questions (
                id VARCHAR PRIMARY KEY,
                teacher_id VARCHAR NOT NULL REFERENCES users(id),
                subject VARCHAR(100) NOT NULL DEFAULT '',
                topic VARCHAR(100) NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                type VARCHAR(20) DEFAULT 'mcq',
                options TEXT,
                correct_answer TEXT,
                difficulty VARCHAR(10) DEFAULT 'medium',
                points INTEGER DEFAULT 1,
                note TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # ── repetitor_questions: topic sütunu ────────────────────────────────────
        result = await conn.execute(sa.text("PRAGMA table_info(repetitor_questions)"))
        rq_cols = {row[1] for row in result.fetchall()}
        if "topic" not in rq_cols:
            await _add_col(conn, "repetitor_questions", "topic", "VARCHAR(100) DEFAULT ''")

        # ── Repetitor topics ──────────────────────────────────────────────────
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS repetitor_topics (
                id VARCHAR PRIMARY KEY,
                teacher_id VARCHAR NOT NULL REFERENCES users(id),
                subject VARCHAR(100) NOT NULL DEFAULT '',
                name VARCHAR(100) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.commit()

        # ── Repetitor exams ────────────────────────────────────────────────────
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS repetitor_exams (
                id VARCHAR PRIMARY KEY,
                teacher_id VARCHAR NOT NULL REFERENCES users(id),
                title VARCHAR(200) NOT NULL,
                subject VARCHAR(100) DEFAULT '',
                duration_min INTEGER DEFAULT 45,
                total_points INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS repetitor_exam_questions (
                id VARCHAR PRIMARY KEY,
                exam_id VARCHAR NOT NULL REFERENCES repetitor_exams(id),
                question_id VARCHAR NOT NULL REFERENCES repetitor_questions(id),
                order_num INTEGER DEFAULT 0
            )
        """))

        # ── Live sessions ──────────────────────────────────────────────────────
        await conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS live_sessions (
                id VARCHAR PRIMARY KEY,
                teacher_id VARCHAR NOT NULL REFERENCES users(id),
                class_id VARCHAR REFERENCES classes(id),
                title VARCHAR(200) NOT NULL,
                description TEXT,
                scheduled_at VARCHAR(30),
                started_at VARCHAR(30),
                ended_at VARCHAR(30),
                status VARCHAR(20) DEFAULT 'scheduled',
                room_name VARCHAR(100) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await conn.commit()


async def _start_rag_indexer():
    """Startup-da RAG indekslərini yenilə (background task)."""
    import asyncio
    from app.database import AsyncSessionLocal

    def _safe_log(msg: str) -> None:
        # Windows konsolu (cp1252) Azərbaycan hərflərini (İ, ə) çap edə bilmir →
        # ASCII-yə təhlükəsiz şəkildə endir ki, print() UnicodeEncodeError atmasın.
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode("ascii", "replace").decode("ascii"))

    async def _run():
        try:
            from app.services.indexer import run_full_index
            async with AsyncSessionLocal() as db:
                result = await run_full_index(db)
                _safe_log(f"[RAG] Indexleme: {result}")
        except Exception as e:
            _safe_log(f"[RAG] Indexleme xetasi (Ollama islemirmi?): {e}")

    asyncio.create_task(_run())


async def _start_exam_scheduler():
    """Planlaşdırılmış imtahanları avtomatik aktivləşdir/bitir (hər 30 saniyədə)."""
    import asyncio
    from datetime import datetime, timedelta
    from app.database import AsyncSessionLocal
    import sqlalchemy as sa

    async def _tick():
        from app.models.exam import Exam, Question
        now = datetime.now()
        async with AsyncSessionLocal() as db:
            # ── AKTİVLƏŞDİR: cədvəl vaxtı çatmış, hələ avto-işlənməmiş, sualı olan ──
            res = await db.execute(
                sa.select(Exam).where(
                    Exam.is_active == False,           # noqa: E712
                    Exam.auto_activated == False,      # noqa: E712
                    Exam.scheduled_at.isnot(None),
                    Exam.scheduled_at <= now,
                )
            )
            for exam in res.scalars().all():
                end = exam.scheduled_at + timedelta(minutes=exam.duration_minutes)
                if now >= end:
                    continue  # pəncərə artıq bağlanıb — aktivləşdirmə
                qc = await db.execute(
                    sa.select(sa.func.count(Question.id)).where(Question.exam_id == exam.id)
                )
                if (qc.scalar_one() or 0) > 0:
                    exam.is_active = True
                    exam.auto_activated = True

            # ── BİT: avto-aktivləşmiş imtahanın pəncərəsi bitib ──
            res2 = await db.execute(
                sa.select(Exam).where(
                    Exam.is_active == True,            # noqa: E712
                    Exam.auto_activated == True,       # noqa: E712
                    Exam.scheduled_at.isnot(None),
                )
            )
            for exam in res2.scalars().all():
                end = exam.scheduled_at + timedelta(minutes=exam.duration_minutes)
                if now >= end:
                    exam.is_active = False

            await db.commit()

    async def _loop():
        while True:
            try:
                await _tick()
            except Exception:
                pass
            await asyncio.sleep(30)

    asyncio.create_task(_loop())


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    await _migrate_db()
    await seed_database()
    await _start_rag_indexer()
    await _start_exam_scheduler()
    print(f"[OK] {settings.APP_NAME} started")
    yield
    print("[STOP] Server stopped")


app = FastAPI(
    title=settings.APP_NAME,
    description="EduAI — AI esasli tehsil platformasi",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(ai.router)
app.include_router(superadmin.router)
app.include_router(invitations.router)
app.include_router(chat.router)
app.include_router(teacher.router)
app.include_router(student.router)
app.include_router(parent.router)
app.include_router(corporate.router)
app.include_router(notifications.router)
app.include_router(messages.router)
app.include_router(timetable.router)
app.include_router(content.router)
app.include_router(repetitor.router)
app.include_router(ws_router.router)
app.include_router(courses_router.router)

# Yüklənmiş faylları xidmət et
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


@app.get("/")
async def root():
    return {"app": settings.APP_NAME, "version": "1.0.0", "status": "isleyir", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "ok"}
