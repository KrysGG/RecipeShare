from flask import Flask, request, jsonify, session, render_template
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from db import get_connection

app = Flask(__name__)
app.config["SECRET_KEY"] = "cambia_esta_clave_en_produccion"
CORS(app, supports_credentials=True)


def success(data=None, message="OK", status=200):
    return jsonify({"success": True, "message": message, "data": data}), status


def error(message="Error", status=400):
    return jsonify({"success": False, "message": message, "data": None}), status


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return error("Debe iniciar sesion para realizar esta accion.", 401)
        return fn(*args, **kwargs)
    return wrapper


def current_user_id():
    return session.get("user_id")

# --- Endpoints de Autenticación ---


@app.route("/")
def index():
    return render_template("index.html")


@app.post("/api/register")
def register():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if len(name) < 3:
        return error("El nombre debe tener al menos 3 caracteres.")
    if "@" not in email or len(email) < 6:
        return error("Debe ingresar un email valido.")
    if len(password) < 6:
        return error("El password debe tener al menos 6 caracteres.")

    password_hash = generate_password_hash(password)
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)",
            (name, email, password_hash)
        )
        conn.commit()
        return success({"id": cursor.lastrowid, "name": name, "email": email}, "Usuario registrado.", 201)
    except Exception:
        conn.rollback()
        return error("El email ya existe o no se pudo registrar el usuario.", 409)
    finally:
        cursor.close()
        conn.close()


@app.post("/api/login")
def login():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if not user or not check_password_hash(user["password_hash"], password):
        return error("Credenciales invalidas.", 401)

    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    return success({"id": user["id"], "name": user["name"], "email": user["email"]}, "Login correcto.")


@app.post("/api/logout")
@login_required
def logout():
    session.clear()
    return success(message="Sesion cerrada.")


@app.get("/api/me")
@login_required
def me():
    return success({"id": session["user_id"], "name": session["user_name"]})

# --- Endpoints de Recetas ---


def validate_recipe_payload(data):
    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    ingredients = data.get("ingredients", "").strip()
    steps = data.get("steps", "").strip()
    prep_minutes = data.get("prep_minutes")

    if len(title) < 3:
        return None, "El titulo debe tener al menos 3 caracteres."
    if len(description) < 10:
        return None, "La descripcion debe tener al menos 10 caracteres."
    if len(ingredients) < 10:
        return None, "Debe incluir ingredientes suficientes."
    if len(steps) < 10:
        return None, "Debe incluir pasos suficientes."

    try:
        prep_minutes = int(prep_minutes)
        if prep_minutes <= 0:
            return None, "El tiempo debe ser mayor de 0."
    except Exception:
        return None, "El tiempo debe ser un numero entero."

    return {
        "title": title, "description": description,
        "ingredients": ingredients, "steps": steps,
        "prep_minutes": prep_minutes
    }, None


@app.get("/api/recipes")
def get_recipes():
    sort = request.args.get("sort", "recent")
    order_clause = "likes_count DESC, r.created_at DESC" if sort == "likes" else "r.created_at DESC"

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    query = f"""
        SELECT r.id, r.title, r.description, r.prep_minutes, r.created_at,
        u.name AS author_name, COUNT(l.id) AS likes_count
        FROM recipes r
        JOIN users u ON r.user_id = u.id
        LEFT JOIN recipe_likes l ON r.id = l.recipe_id
        GROUP BY r.id, r.title, r.description, r.prep_minutes, r.created_at, u.name
        ORDER BY {order_clause}
    """
    cursor.execute(query)
    recipes = cursor.fetchall()
    cursor.close()
    conn.close()
    return success(recipes)


@app.post("/api/recipes")
@login_required
def create_recipe():
    payload, validation_error = validate_recipe_payload(
        request.get_json() or {})
    if validation_error:
        return error(validation_error)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO recipes (user_id, title, description, ingredients, steps, prep_minutes)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (current_user_id(), payload["title"], payload["description"], payload["ingredients"], payload["steps"], payload["prep_minutes"]))

    conn.commit()
    recipe_id = cursor.lastrowid
    cursor.close()
    conn.close()

    return success({"id": recipe_id}, "Receta publicada.", 201)


@app.put("/api/recipes/<int:recipe_id>")
@login_required
def update_recipe(recipe_id):
    payload, validation_error = validate_recipe_payload(
        request.get_json() or {})
    if validation_error:
        return error(validation_error)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE recipes SET title=%s, description=%s, ingredients=%s, steps=%s, prep_minutes=%s
        WHERE id=%s AND user_id=%s
    """, (payload["title"], payload["description"], payload["ingredients"], payload["steps"], payload["prep_minutes"], recipe_id, current_user_id()))

    conn.commit()
    affected = cursor.rowcount
    cursor.close()
    conn.close()

    if affected == 0:
        return error("No se encontro la receta o no tiene permiso para editarla.", 404)
    return success(message="Receta actualizada.")

# --- Endpoints de Favoritos y Likes ---


@app.post("/api/recipes/<int:recipe_id>/like")
@login_required
def add_like(recipe_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO recipe_likes (user_id, recipe_id) VALUES (%s, %s)",
                       (current_user_id(), recipe_id))
        conn.commit()
        return success(message="Like registrado.", status=201)
    except Exception:
        conn.rollback()
        return error("Ya habia dado like a esta receta o la receta no existe.", 409)
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    app.run(debug=True)
