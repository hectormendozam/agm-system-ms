import psycopg2
from psycopg2 import sql
import bcrypt

# Configuración de conexión centralizada (basada en docker-compose)
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "postgres",
    "password": "root"
}

# Lista de bases de datos a limpiar
DATABASES_TO_RESET = [
    "agm_auth_db",
    "agm_notificaciones_db",
    "attendance_db",
    "agm_docentes_db",
    # "agm_periodos_materias_db", # Django - se maneja con cuidado
    "reports_db",
    "agm_calificaciones_db"
]

def get_password_hash(password: str) -> str:
    # bcrypt requiere que el input sean bytes
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    # Retornamos como string para la base de datos
    return hashed.decode('utf-8')

def reset_databases():
    print("--- Iniciando limpieza de bases de datos ---")
    
    # 1. Limpiar microservicios estándar (SQLAlchemy/Raw)
    for db_name in DATABASES_TO_RESET:
        try:
            conn = psycopg2.connect(dbname=db_name, **DB_CONFIG)
            conn.autocommit = True
            cur = conn.cursor()
            
            # Obtener todas las tablas de la base de datos actual (excepto tablas de sistema)
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_type = 'BASE TABLE';
            """)
            tables = [row[0] for row in cur.fetchall()]
            
            if tables:
                # Truncar todas las tablas con RESTART IDENTITY y CASCADE para limpiar FKs
                truncate_query = f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE;"
                cur.execute(truncate_query)
                print(f"[OK] Base de datos '{db_name}' reseteada ({len(tables)} tablas).")
            else:
                print(f"[SKIP] Base de datos '{db_name}' no tiene tablas.")
                
            cur.close()
            conn.close()
        except Exception as e:
            print(f"[ERROR] No se pudo conectar a '{db_name}': {e}")

    # 2. Limpiar base de datos de Django (ms-periodos-materias)
    try:
        db_name = "agm_periodos_materias_db"
        conn = psycopg2.connect(dbname=db_name, **DB_CONFIG)
        conn.autocommit = True
        cur = conn.cursor()
        
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
            AND table_name NOT LIKE 'django_%'
            AND table_name NOT LIKE 'auth_%';
        """)
        django_app_tables = [row[0] for row in cur.fetchall()]
        
        if django_app_tables:
            truncate_query = f"TRUNCATE TABLE {', '.join(django_app_tables)} RESTART IDENTITY CASCADE;"
            cur.execute(truncate_query)
            print(f"[OK] Tablas de aplicación en '{db_name}' reseteadas.")
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[ERROR] No se pudo resetear tablas de Django: {e}")

    # 3. Crear el usuario Admin por defecto en ms-auth
    try:
        db_name = "agm_auth_db"
        conn = psycopg2.connect(dbname=db_name, **DB_CONFIG)
        conn.autocommit = True
        cur = conn.cursor()
        
        admin_email = "admin@buap.mx"
        admin_pass = "password123"
        
        # Generar el hash usando la librería bcrypt directamente
        hashed_pass = get_password_hash(admin_pass)
        
        cur.execute("INSERT INTO usuarios (email, password_hash, rol) VALUES (%s, %s, %s) ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash, rol = EXCLUDED.rol;", 
                    (admin_email, hashed_pass, "ADMIN"))
        
        print(f"\n--- Usuario de prueba listo ---")
        print(f"Email: {admin_email}")
        print(f"Password: {admin_pass}")
        print(f"Rol: ADMIN")
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[ERROR] No se pudo crear el usuario admin: {e}")

if __name__ == "__main__":
    reset_databases()

if __name__ == "__main__":
    reset_databases()
