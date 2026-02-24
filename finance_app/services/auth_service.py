from finance_app.database import get_connection
from werkzeug.security import check_password_hash


def autenticar_usuario(username: str, password: str):
    if not username or not password:
        return None

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, username, password_hash, ativo
            FROM usuarios
            WHERE username = ?;
            """,
            (username,),
        )
        row = cur.fetchone()
        if not row:
            return None
        if not bool(row["ativo"]):
            return None
        if not check_password_hash(row["password_hash"], password):
            return None
        return {"id": row["id"], "username": row["username"]}
    finally:
        conn.close()
