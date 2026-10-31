import os
import base64
import secrets
import sqlite3
from pathlib import Path
from functools import wraps
from flask import Flask, request, redirect, url_for, session, flash, Response

BASE = Path(__file__).resolve().parent
DB_FILE = BASE / "rafin.db"

app = Flask(__name__)
app.secret_key = os.environ.get("RAFIN_SECRET_KEY", "rafin-txt-change-this-secret")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

ADMIN_PASSWORD = os.environ.get("RAFIN_ADMIN_PASSWORD", "RAFIN_888")
TELEGRAM_LINK = "https://t.me/alien_boss_676"
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

DEFAULT_PROFILE_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

# ---------- ডেটাবেস ----------
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                price TEXT NOT NULL,
                category TEXT,
                description TEXT,
                image_mime TEXT,
                image_data BLOB,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.commit()

init_db()

def list_products():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, name, price, category, description,
                   (image_data IS NOT NULL) AS has_image
            FROM products ORDER BY created_at DESC
        """).fetchall()
    return [dict(r) for r in rows]

def get_product(pid):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    return dict(row) if row else None

def get_site_photo_key():
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='site_photo'").fetchone()
    return row["value"] if row else None

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            flash("এই অংশে ঢুকতে আগে প্রশাসক হিসেবে প্রবেশ করো।", "error")
            return redirect(url_for("home"))
        return fn(*args, **kwargs)
    return wrapper

def ext_ok(filename, allowed):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed

def file_to_base64(file):
    if not file or not file.filename or not ext_ok(file.filename, IMAGE_EXTENSIONS):
        return None, None
    data = file.read()
    if not data:
        return None, None
    ext = file.filename.rsplit(".", 1)[1].lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    return mime, data

# ---------- রুট ----------
@app.route("/")
def home():
    return render_template_string(
        PAGE,
        products=list_products(),
        is_admin=bool(session.get("admin")),
        show_login=request.args.get("login") == "1",
        telegram_link=TELEGRAM_LINK,
    )

@app.post("/login")
def login():
    if secrets.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
        session["admin"] = True
        flash("প্রশাসক প্যানেলে প্রবেশ সফল হয়েছে।", "success")
    else:
        flash("গোপন সংকেত সঠিক নয়।", "error")
    return redirect(url_for("home"))

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.post("/add")
@admin_required
def add_item():
    name = request.form.get("name", "").strip()
    price = request.form.get("price", "").strip()
    if not name or not price:
        flash("পণ্যের নাম ও দাম লিখতে হবে।", "error")
        return redirect(url_for("home"))

    mime, data = file_to_base64(request.files.get("photo"))
    with get_db() as conn:
        conn.execute(
            "INSERT INTO products (id,name,price,category,description,image_mime,image_data) VALUES (?,?,?,?,?,?,?)",
            (secrets.token_hex(6), name, price, request.form.get("category", "").strip(),
             request.form.get("description", "").strip(), mime, data),
        )
        conn.commit()
    flash("নতুন পণ্য যোগ হয়েছে।", "success")
    return redirect(url_for("home"))

@app.route("/edit/<pid>", methods=["GET", "POST"])
@admin_required
def edit_item(pid):
    item = get_product(pid)
    if not item:
        flash("পণ্যটি পাওয়া যায়নি।", "error")
        return redirect(url_for("home"))

    if request.method == "POST":
        mime, data = file_to_base64(request.files.get("photo"))
        with get_db() as conn:
            if data:
                conn.execute("UPDATE products SET name=?,price=?,category=?,description=?,image_mime=?,image_data=? WHERE id=?",
                    (request.form.get("name", "").strip(), request.form.get("price", "").strip(),
                     request.form.get("category", "").strip(), request.form.get("description", "").strip(), mime, data, pid))
            else:
                conn.execute("UPDATE products SET name=?,price=?,category=?,description=? WHERE id=?",
                    (request.form.get("name", "").strip(), request.form.get("price", "").strip(),
                     request.form.get("category", "").strip(), request.form.get("description", "").strip(), pid))
            conn.commit()
        flash("পণ্যের তথ্য বদলানো হয়েছে।", "success")
        return redirect(url_for("home"))

    return render_template_string(EDIT_PAGE, item=item)

@app.post("/delete/<pid>")
@admin_required
def delete_item(pid):
    with get_db() as conn:
        conn.execute("DELETE FROM products WHERE id=?", (pid,))
        conn.commit()
    flash("পণ্য মুছে ফেলা হয়েছে।", "success")
    return redirect(url_for("home"))

@app.get("/product-image/<pid>")
def product_image(pid):
    with get_db() as conn:
        row = conn.execute("SELECT image_mime, image_data FROM products WHERE id=?", (pid,)).fetchone()
    if not row or not row["image_data"]:
        return "", 404
    return Response(row["image_data"], mimetype=row["image_mime"] or "image/png")

@app.post("/site-photo/update")
@admin_required
def update_site_photo():
    mime, data = file_to_base64(request.files.get("site_photo"))
    if not data:
        flash("একটি JPG, PNG, WEBP বা GIF ছবি বেছে নাও।", "error")
        return redirect(url_for("home"))
    with get_db() as conn:
        conn.execute("INSERT INTO settings (key,value) VALUES ('site_photo',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (f"{mime}|{base64.b64encode(data).decode()}",))
        conn.commit()
    flash("সাইটের ছবি পরিবর্তন হয়েছে।", "success")
    return redirect(url_for("home"))

@app.get("/site-photo")
def site_photo():
    key = get_site_photo_key()
    if key:
        mime, b64 = key.split("|", 1)
        return Response(base64.b64decode(b64), mimetype=mime)
    return Response(base64.b64decode(DEFAULT_PROFILE_B64), mimetype="image/png")

@app.errorhandler(413)
def too_large(_e):
    flash("ফাইলটি অনেক বড়। ২৫ এমবির মধ্যে রাখো।", "error")
    return redirect(url_for("home"))

# ---------- HTML পেজসমূহ ----------
PAGE = r"""
<!doctype html>
<html lang="bn"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RAFIN TxT</title>
<style>
:root{--bg:#090515;--line:#922cff;--pink:#d51dff;--txt:#fff;--muted:#c2b1d9}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 50% -20%,#39105d 0,transparent 45%),var(--bg);color:var(--txt);font-family:system-ui,"Noto Sans Bengali",sans-serif}
header{position:sticky;top:0;z-index:3;background:#090515ee;border-bottom:1px solid #7722b7;padding:13px 4%;display:flex;align-items:center;justify-content:space-between;gap:12px;backdrop-filter:blur(12px)}
.brand{font-size:27px;font-weight:950;font-style:italic}.brand span{color:#e13cff}
button,.topbtn{font:inherit;font-weight:800;color:#fff;background:linear-gradient(110deg,#791cff,#d51dff);border:1px solid #a43aff;border-radius:12px;padding:11px 16px;cursor:pointer;text-decoration:none;display:inline-block}
main{max-width:1120px;margin:auto;padding:24px 16px 55px}
.hero{display:grid;grid-template-columns:1.05fr .95fr;align-items:center;gap:20px;padding:22px;border:1px solid var(--line);border-radius:24px;background:linear-gradient(125deg,#180b32,#0c0920 55%,#2a0c42);box-shadow:0 0 30px #8b21ff25;overflow:hidden}
.hero-copy{text-align:center;padding:20px 8px}.hero h1{font-size:clamp(42px,7vw,72px);margin:0;text-shadow:0 0 20px #b328ff}.hero h1 span{color:#e13cff}.hero p{color:#e0d3f5;font-size:17px}
.portrait{width:100%;max-height:480px;object-fit:cover;object-position:center 25%;border-radius:18px;border:2px solid #b52cff;box-shadow:0 0 25px #d51dff55}
h2{margin:28px 0 14px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:15px}
.product{border:1px solid #7026a9;background:linear-gradient(145deg,#21113f,#10091f);border-radius:18px;padding:12px;overflow:hidden}
.product img{width:100%;height:165px;object-fit:cover;border-radius:12px;background:#10091f}.product h3{margin:10px 0 4px}
.muted{color:var(--muted);font-size:13px}.price{color:#ffe45a;font-weight:900;margin:8px 0}
.buy{width:100%;text-align:center;border-radius:11px;padding:12px;background:linear-gradient(100deg,#751aff,#d51dff);color:white;font-weight:850;text-decoration:none;display:block}
.empty{border:1px dashed #7131a9;border-radius:18px;padding:30px 15px;text-align:center;color:var(--muted);background:#110a21}
.panel{border:1px solid #7026a9;background:linear-gradient(145deg,#21113f,#10091f);border-radius:18px;padding:17px;margin-top:15px}
.flash{max-width:1120px;margin:12px auto 0;padding:11px 15px;border-radius:12px;background:#2b1746;border:1px solid #8731c4}.flash.error{border-color:#d34b80;color:#ffd6e5}.flash.success{border-color:#46ad79;color:#d6ffe8}
.modalback{position:fixed;inset:0;background:#000b;display:flex;align-items:center;justify-content:center;padding:18px;z-index:10}
.modal{width:min(440px,100%);background:#170d2d;border:1px solid var(--line);border-radius:20px;padding:22px;box-shadow:0 0 35px #a329ff44}
.modal input,.form input,.form textarea{width:100%;padding:12px;margin:7px 0;background:#090515;color:#fff;border:1px solid #7130a4;border-radius:10px;font:inherit}
.modal .rowbtn{display:flex;gap:8px}.modal .rowbtn button{flex:1}.secondary{background:#24153c;border-color:#7130a4}
.adminhead{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.form{display:grid;grid-template-columns:1fr 1fr;gap:8px}.form textarea,.form .wide{grid-column:1/-1}
.items{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid #392051}
.items img{width:65px;height:58px;object-fit:cover;border-radius:8px}.info{flex:1;min-width:0}.actions{display:flex;gap:7px}
.small{padding:8px 11px;font-size:13px}.danger{background:#56142f;border-color:#b33165}
footer{text-align:center;border-top:1px solid #4e1c78;color:#9e8bb8;padding:22px}
@media(max-width:650px){header{padding:12px 3%}.brand{font-size:22px}.topbtn{font-size:13px;padding:10px}.hero{grid-template-columns:1fr;padding:14px}.hero-copy{padding:12px 4px}.portrait{max-height:390px;object-position:center 20%}.form{grid-template-columns:1fr}.form textarea,.form .wide{grid-column:auto}.items{align-items:flex-start}.items img{width:55px;height:52px}.actions{flex-direction:column}}
#hidden-music { display: none; }
</style></head><body>

<!-- লুকানো মিউজিক প্লেয়ার -->
<audio id="hidden-music" loop>
    <source src="{{ url_for('static', filename='music/song.mp3') }}" type="audio/mpeg">
</audio>
<script>
    document.addEventListener('click', function() {
        var audio = document.getElementById('hidden-music');
        if (audio && audio.paused) {
            audio.volume = 0.5;
            audio.play().catch(function(e) { console.log("Autoplay blocked"); });
        }
    });
</script>

<header><div class="brand">👑 RAFIN <span>TxT</span></div>
{% if is_admin %}<a class="topbtn" href="{{ url_for('logout') }}">বের হও</a>{% else %}<a class="topbtn" href="{{ url_for('home', login='1') }}">⚙ প্রশাসক প্রবেশ</a>{% endif %}
</header>
{% with messages=get_flashed_messages(with_categories=true) %}{% for category,message in messages %}<div class="flash {{category}}">{{message}}</div>{% endfor %}{% endwith %}
<main>
{% if is_admin %}
<div class="adminhead"><div><h2 style="margin:0">⚙ RAFIN TxT প্রশাসক প্যানেল</h2><div class="muted">এখান থেকে পণ্য নিয়ন্ত্রণ করো</div></div><a class="topbtn" href="{{ url_for('home') }}">সাইট দেখো</a></div>
<section class="panel"><h2 style="margin:0 0 12px">＋ নতুন পণ্য যোগ করো</h2>
<form class="form" method="post" action="{{ url_for('add_item') }}" enctype="multipart/form-data">
<input name="name" placeholder="পণ্যের নাম *" required><input name="price" placeholder="দাম *" required>
<input name="category" placeholder="ধরন"><input type="file" name="photo" accept="image/*">
<textarea name="description" placeholder="পণ্যের বিবরণ"></textarea><button class="wide">＋ পণ্য সংরক্ষণ</button>
</form><p class="muted">নিজের ছবি দিয়ে পণ্য যোগ করতে পারবে।</p></section>
<section class="panel"><h2 style="margin:0 0 10px">পণ্য পরিচালনা</h2>
{% for p in products %}<div class="items">{% if p.has_image %}<img src="{{ url_for('product_image', pid=p.id) }}">{% endif %}<div class="info"><b>{{p.name}}</b><div class="muted">{{p.category}} · {{p.price}}</div><div class="muted">{{p.description}}</div></div><div class="actions"><a class="topbtn small" href="{{ url_for('edit_item', pid=p.id) }}">সংশোধন</a><form method="post" action="{{ url_for('delete_item', pid=p.id) }}" onsubmit="return confirm('এই পণ্যটি মুছে ফেলবে?')"><button class="small danger">মুছুন</button></form></div></div>{% else %}<div class="empty">এখনো কোনো পণ্য যোগ করা হয়নি।</div>{% endfor %}
</section>
<section class="panel"><h2 style="margin:0 0 12px">🖼️ নিজের ছবি বসাও (BOSS ছবি)</h2>
<form class="form" method="post" action="{{ url_for('update_site_photo') }}" enctype="multipart/form-data">
<input class="wide" type="file" name="site_photo" accept="image/*" required>
<button class="wide">ছবি পরিবর্তন করো</button>
</form><p class="muted">ফোনের গ্যালারি থেকে আপনার BOSS ছবিটি বেছে আপলোড করুন।</p></section>
{% else %}
<section class="hero"><div class="hero-copy"><h1>RAFIN <span>TxT</span></h1><p>আমার অফিসিয়াল সাইটে স্বাগতম</p></div><img class="portrait" src="{{ url_for('site_photo') }}?t={{ range(1,999999)|random }}" alt="RAFIN TxT"></section>
<h2>✨ আমাদের পণ্যসমূহ</h2><section class="grid">
{% for p in products %}<article class="product">{% if p.has_image %}<img src="{{ url_for('product_image', pid=p.id) }}" alt="">{% endif %}<h3>{{p.name}}</h3><div class="muted">{{p.category}}</div><p>{{p.description}}</p><div class="price">{{p.price}}</div><a class="buy" href="{{telegram_link}}" target="_blank" rel="noopener">কিনতে যোগাযোগ করো</a></article>{% else %}<div class="empty">এখনো কোনো পণ্য যোগ করা হয়নি।</div>{% endfor %}
</section>
{% endif %}
</main><footer>© ২০২৬ RAFIN TxT · সর্বস্বত্ব সংরক্ষিত</footer>
{% if show_login and not is_admin %}<div class="modalback" onclick="if(event.target===this)location.href='/'"><div class="modal"><h2 style="margin:0 0 8px">🔐 প্রশাসক প্রবেশ</h2><p class="muted">শুধু সাইটের মালিকের জন্য</p><form method="post" action="{{ url_for('login') }}"><input type="password" name="password" placeholder="প্রবেশের গোপন সংকেত" required autofocus><div class="rowbtn"><button type="submit">প্রবেশ করো</button><button type="button" class="secondary" onclick="location.href='/'">বন্ধ করো</button></div></form></div></div>{% endif %}
</body></html>
"""

EDIT_PAGE = r"""
<!doctype html><html lang="bn"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RAFIN TxT · সংশোধন</title>
<style>body{background:#090515;color:#fff;font-family:system-ui;padding:20px}
input,textarea{width:100%;padding:12px;margin:6px 0;background:#110a21;color:#fff;border:1px solid #7130a4;border-radius:10px}
button{padding:12px 18px;background:linear-gradient(110deg,#791cff,#d51dff);color:#fff;border:none;border-radius:12px;font-weight:800;cursor:pointer}
a{color:#e13cff}</style></head><body>
<h2>RAFIN TxT · পণ্য সংশোধন</h2>
<form method="post" enctype="multipart/form-data">
<input name="name" value="{{item.name}}" required placeholder="পণ্যের নাম">
<input name="price" value="{{item.price}}" required placeholder="দাম">
<input name="category" value="{{item.category or ''}}" placeholder="ধরন">
<textarea name="description" placeholder="বিবরণ">{{item.description or ''}}</textarea>
<input type="file" name="photo" accept="image/*">
<button type="submit">সংরক্ষণ করো</button>
</form>
<p><a href="{{ url_for('home') }}">← প্রশাসক প্যানেলে ফেরত যাও</a></p>
</body></html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)