from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
import sqlite3, hashlib, os, json, io
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)
app.secret_key = "taskquest_secret_2025_xD"
DB = "taskquest.db"

# ─── DB SETUP ────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            xp INTEGER DEFAULT 0,
            total_completed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            date TEXT NOT NULL,
            priority TEXT DEFAULT 'media',
            completed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)
    conn.commit()
    conn.close()

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

# ─── LEVEL UTILS ─────────────────────────────────────────────
def xp_for_level(level):
    return level * 100

def calc_level(xp):
    level, total = 1, 0
    while True:
        needed = xp_for_level(level)
        if total + needed > xp:
            return level, xp - total, needed
        total += needed
        level += 1

PRIORITY_XP = {"alta": 50, "media": 30, "baja": 15}

# ─── AUTH ─────────────────────────────────────────────────────
def logged_in():
    return "user_id" in session

@app.route("/")
def index():
    if not logged_in():
        return redirect(url_for("login"))
    return render_template("index.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    data = request.json
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE (username=? OR email=?) AND password=?",
        (data["username"], data["username"], hash_pw(data["password"]))
    ).fetchone()
    conn.close()
    if not user:
        return jsonify({"success": False, "error": "Usuario o contraseña incorrectos"})
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    return jsonify({"success": True})

@app.route("/register", methods=["POST"])
def register():
    data = request.json
    if len(data["password"]) < 6:
        return jsonify({"success": False, "error": "La contraseña debe tener al menos 6 caracteres"})
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, email, password) VALUES (?,?,?)",
            (data["username"].strip(), data["email"].strip().lower(), hash_pw(data["password"]))
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE username=?", (data["username"],)).fetchone()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        conn.close()
        return jsonify({"success": True})
    except sqlite3.IntegrityError as e:
        conn.close()
        if "username" in str(e):
            return jsonify({"success": False, "error": "Ese nombre de usuario ya existe"})
        return jsonify({"success": False, "error": "Ese email ya está registrado"})

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ─── API ──────────────────────────────────────────────────────
@app.route("/api/data")
def get_data():
    if not logged_in(): return jsonify({"error":"unauthorized"}), 401
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    tasks = conn.execute("SELECT * FROM tasks WHERE user_id=? ORDER BY date", (session["user_id"],)).fetchall()
    conn.close()
    level, current_xp, needed_xp = calc_level(user["xp"])
    return jsonify({
        "username": user["username"],
        "tasks": [dict(t) for t in tasks],
        "xp": user["xp"],
        "level": level,
        "current_xp": current_xp,
        "needed_xp": needed_xp,
        "total_completed": user["total_completed"]
    })

@app.route("/api/tasks", methods=["POST"])
def add_task():
    if not logged_in(): return jsonify({"error":"unauthorized"}), 401
    data = request.json
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO tasks (user_id, title, description, date, priority) VALUES (?,?,?,?,?)",
        (session["user_id"], data["title"], data.get("description",""), data["date"], data.get("priority","media"))
    )
    task_id = cur.lastrowid
    task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    conn.commit(); conn.close()
    return jsonify({"success": True, "task": dict(task)})

@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
def update_task(task_id):
    if not logged_in(): return jsonify({"error":"unauthorized"}), 401
    data = request.json
    conn = get_db()
    conn.execute(
        "UPDATE tasks SET title=?, description=?, date=?, priority=? WHERE id=? AND user_id=?",
        (data["title"], data.get("description",""), data["date"], data.get("priority","media"), task_id, session["user_id"])
    )
    task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    conn.commit(); conn.close()
    return jsonify({"success": True, "task": dict(task)})

@app.route("/api/tasks/<int:task_id>/complete", methods=["POST"])
def complete_task(task_id):
    if not logged_in(): return jsonify({"error":"unauthorized"}), 401
    conn = get_db()
    task = conn.execute("SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, session["user_id"])).fetchone()
    if not task or task["completed"]:
        conn.close()
        return jsonify({"success": False})
    xp_gained = PRIORITY_XP.get(task["priority"], 30)
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    old_level, _, _ = calc_level(user["xp"])
    new_xp = user["xp"] + xp_gained
    new_completed = user["total_completed"] + 1
    conn.execute("UPDATE tasks SET completed=1, completed_at=? WHERE id=?", (datetime.now().isoformat(), task_id))
    conn.execute("UPDATE users SET xp=?, total_completed=? WHERE id=?", (new_xp, new_completed, session["user_id"]))
    conn.commit()
    new_level, current_xp, needed_xp = calc_level(new_xp)
    conn.close()
    return jsonify({
        "success": True,
        "xp_gained": xp_gained,
        "leveled_up": new_level > old_level,
        "level": new_level,
        "current_xp": current_xp,
        "needed_xp": needed_xp,
        "total_xp": new_xp
    })

@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id):
    if not logged_in(): return jsonify({"error":"unauthorized"}), 401
    conn = get_db()
    conn.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, session["user_id"]))
    conn.commit(); conn.close()
    return jsonify({"success": True})

# ─── LEVEL UP IMAGE ───────────────────────────────────────────
@app.route("/api/levelup-image/<int:level>")
def levelup_image(level):
    if not logged_in(): return jsonify({"error":"unauthorized"}), 401
    username = session.get("username", "Héroe")

    W, H = 800, 400
    img = Image.new("RGB", (W, H), color=(14, 15, 20))
    draw = ImageDraw.Draw(img)

    # background stars
    import random
    random.seed(level * 42)
    for _ in range(120):
        x, y = random.randint(0, W), random.randint(0, H)
        r = random.randint(1, 3)
        alpha = random.randint(80, 200)
        draw.ellipse([x-r, y-r, x+r, y+r], fill=(alpha, alpha, alpha+30))

    # gradient-like glow circle
    for i in range(60, 0, -1):
        alpha = int(i * 1.5)
        c = (80 + i, 60 + i, 200 + i//2)
        draw.ellipse([W//2 - i*2, H//2 - i*2, W//2 + i*2, H//2 + i*2], fill=c)

    # try to load a font, fallback to default
    try:
        font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
        font_med = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
    except:
        font_big = ImageFont.load_default()
        font_med = font_big
        font_small = font_big

    messages_es = [
        "Cada vez eres más responsable, ¡sigue así!",
        "Tu disciplina te llevará lejos, ¡no pares!",
        "¡Eres imparable! La constancia es tu superpoder.",
        "Cada tarea completada es un paso hacia el éxito.",
        "¡Increíble progreso! Sigue conquistando tus metas.",
    ]
    messages_en = [
        "You're becoming unstoppable, keep going!",
        "Consistency is your superpower. Never stop!",
        "Every task done brings you closer to greatness.",
        "Your dedication is truly inspiring. Level up!",
        "You're on fire! The best is yet to come.",
    ]
    idx = (level - 1) % len(messages_es)
    msg = messages_es[idx] if level % 2 != 0 else messages_en[idx]

    # level badge text
    lvl_text = f"NIVEL {level}"
    bb = draw.textbbox((0,0), lvl_text, font=font_big)
    tw = bb[2] - bb[0]
    draw.text(((W - tw)//2, 80), lvl_text, font=font_big, fill=(255, 220, 80))

    # username
    name_text = f"¡Felicidades, {username}!"
    bb2 = draw.textbbox((0,0), name_text, font=font_med)
    tw2 = bb2[2] - bb2[0]
    draw.text(((W - tw2)//2, 160), name_text, font=font_med, fill=(255, 255, 255))

    # motivational message (wrap if needed)
    words = msg.split()
    lines, line = [], ""
    for w in words:
        test = line + (" " if line else "") + w
        bb3 = draw.textbbox((0,0), test, font=font_small)
        if bb3[2] - bb3[0] > W - 100 and line:
            lines.append(line); line = w
        else:
            line = test
    if line: lines.append(line)

    y_msg = 230
    for ln in lines:
        bb4 = draw.textbbox((0,0), ln, font=font_small)
        tw4 = bb4[2] - bb4[0]
        draw.text(((W - tw4)//2, y_msg), ln, font=font_small, fill=(180, 170, 240))
        y_msg += 30

    # stars decoration
    star_y = 320
    for sx in [W//2 - 60, W//2, W//2 + 60]:
        draw.text((sx - 8, star_y), "★", font=font_small, fill=(255, 220, 80))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

if __name__ == "__main__":
    init_db()
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
