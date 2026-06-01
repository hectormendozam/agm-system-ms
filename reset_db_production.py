import os
import psycopg2
import bcrypt

DB_URLS = {
    "auth":              os.environ["DB_URL_AUTH"],
    "periodos_materias": os.environ["DB_URL_PERIODOS"],
    "docentes":          os.environ["DB_URL_DOCENTES"],
    "calificaciones":    os.environ["DB_URL_CALIFICACIONES"],
    "asistencias":       os.environ["DB_URL_ASISTENCIAS"],
    "notificaciones":    os.environ["DB_URL_NOTIFICACIONES"],
    "reportes":          os.environ["DB_URL_REPORTES"],
}


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def reset_service(name: str, url: str, skip_tables: list[str] = []):
    try:
        conn = psycopg2.connect(url, sslmode="require")
        conn.autocommit = True
        cur = conn.cursor()

        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
        """)
        tables = [r[0] for r in cur.fetchall() if r[0] not in skip_tables]

        if tables:
            cur.execute(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE;")
            print(f"[OK] {name} reseteado ({len(tables)} tablas).")
        else:
            print(f"[SKIP] {name} sin tablas.")

        cur.close()
        conn.close()
    except Exception as e:
        print(f"[ERROR] {name}: {e}")


def create_admin(url: str):
    try:
        conn = psycopg2.connect(url, sslmode="require")
        conn.autocommit = True
        cur = conn.cursor()

        email    = "admin@buap.mx"
        password = "password123"
        hashed   = get_password_hash(password)

        cur.execute(
            "INSERT INTO usuarios (email, password_hash, rol) VALUES (%s, %s, %s) "
            "ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash, rol = EXCLUDED.rol;",
            (email, hashed, "ADMIN")
        )
        print(f"\n--- Usuario admin listo ---")
        print(f"Email:    {email}")
        print(f"Password: {password}")
        print(f"Rol:      ADMIN")

        cur.close()
        conn.close()
    except Exception as e:
        print(f"[ERROR] creando admin: {e}")


def reset_all():
    print("--- Limpiando bases de datos de PRODUCCIÓN (Railway) ---\n")

    for name in ["notificaciones", "docentes", "calificaciones", "asistencias", "reportes"]:
        reset_service(name, DB_URLS[name])

    DJANGO_SKIP = [
        "django_migrations", "django_content_type", "django_session",
        "django_admin_log", "auth_permission", "auth_group",
        "auth_group_permissions", "auth_user", "auth_user_groups",
        "auth_user_user_permissions",
    ]
    reset_service("periodos_materias", DB_URLS["periodos_materias"], skip_tables=DJANGO_SKIP)

    reset_service("auth", DB_URLS["auth"])
    create_admin(DB_URLS["auth"])


if __name__ == "__main__":
    reset_all()
