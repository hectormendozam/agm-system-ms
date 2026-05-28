import psycopg2
import bcrypt

# Una URL por microservicio (Railway → cada servicio tiene su propio Postgres)
DB_URLS = {
    "auth":              "postgresql://postgres:***REMOVED***@kodama.proxy.rlwy.net:19388/railway",
    "periodos_materias": "postgresql://postgres:***REMOVED***@zephyr.proxy.rlwy.net:24431/railway",
    "docentes":          "postgresql://postgres:***REMOVED***@zephyr.proxy.rlwy.net:27214/railway",
    "calificaciones":    "postgresql://postgres:***REMOVED***@zephyr.proxy.rlwy.net:12701/railway",
    "asistencias":       "postgresql://postgres:***REMOVED***@zephyr.proxy.rlwy.net:24819/railway",
    "notificaciones":    "postgresql://postgres:***REMOVED***@kodama.proxy.rlwy.net:36636/railway",
    "reportes":          "postgresql://postgres:***REMOVED***@zephyr.proxy.rlwy.net:47235/railway",
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

    # Servicios estándar
    for name in ["notificaciones", "docentes", "calificaciones", "asistencias", "reportes"]:
        reset_service(name, DB_URLS[name])

    # Django: omitir tablas internas de Django/auth
    DJANGO_SKIP = [
        "django_migrations", "django_content_type", "django_session",
        "django_admin_log", "auth_permission", "auth_group",
        "auth_group_permissions", "auth_user", "auth_user_groups",
        "auth_user_user_permissions",
    ]
    reset_service("periodos_materias", DB_URLS["periodos_materias"], skip_tables=DJANGO_SKIP)

    # Auth: resetear y recrear admin
    reset_service("auth", DB_URLS["auth"])
    create_admin(DB_URLS["auth"])


if __name__ == "__main__":
    reset_all()
