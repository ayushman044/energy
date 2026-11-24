import os, time, uuid, secrets
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, session, send_from_directory, abort)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, func
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE, ".env"))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE, "data"))
UPLOADS = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOADS, exist_ok=True)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
    SQLALCHEMY_DATABASE_URI="sqlite:///" + os.path.join(DATA_DIR, "papers.db"),
    MAX_CONTENT_LENGTH=25 * 1024 * 1024,  # 25 MB per PDF
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
)
db = SQLAlchemy(app)

ADMIN_USER = os.environ.get("ADMIN_USERNAME", "admin")
_pw = os.environ.get("ADMIN_PASSWORD")
ADMIN_HASH = generate_password_hash(_pw) if _pw else None

TOPICS = [
    {"slug": "energy-storage", "name": "Flexible energy storage", "blurb": "Batteries and supercapacitors that bend, stretch or fold without losing performance, built for wearables, e-textiles and portable electronics.", "color": "#0f8b8d"},
    {"slug": "sensors", "name": "Sensors", "blurb": "Chemical, gas, strain and biosensing devices, including the nanomaterials and electrode designs that make them sensitive and selective.", "color": "#6a4fb3"},
    {"slug": "co2-reduction", "name": "Electrochemical CO2 reduction", "blurb": "Using electricity to convert carbon dioxide into fuels and chemicals such as CO, formate, ethylene and methanol, with a focus on catalysts and cell design.", "color": "#2f7d32"},
    {"slug": "her", "name": "Hydrogen evolution reaction", "blurb": "Splitting water at the cathode to produce hydrogen, and the low-cost catalysts that can replace platinum.", "color": "#1d6fd1"},
    {"slug": "coal-gasification", "name": "Coal gasification", "blurb": "Converting coal into syngas (hydrogen and carbon monoxide) by partial oxidation, covering reactor types, process chemistry and cleaner conversion routes.", "color": "#7a5a3a"},
    {"slug": "rare-earths", "name": "Rare earth metals for energy storage", "blurb": "How elements such as lanthanum, cerium and neodymium improve electrodes, electrolytes and catalysts in batteries and supercapacitors.", "color": "#c2410c"},
    {"slug": "mineral-recycling", "name": "Critical minerals recycling", "blurb": "Recovering lithium, cobalt, nickel and rare earths from spent batteries and e-waste through hydrometallurgical, pyrometallurgical and direct recycling routes.", "color": "#b4234a"},
]
TOPIC_MAP = {t["slug"]: t for t in TOPICS}


class Paper(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    authors = db.Column(db.String(400), default="")
    journal = db.Column(db.String(200), default="")
    year = db.Column(db.Integer)
    doi = db.Column(db.String(200), default="")
    abstract = db.Column(db.Text, default="")
    topic = db.Column(db.String(40), nullable=False, index=True)
    filename = db.Column(db.String(80), nullable=False)
    original_name = db.Column(db.String(200), default="paper.pdf")
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


with app.app_context():
    db.create_all()


# ---------- security helpers ----------
@app.before_request
def csrf_protect():
    if request.method == "POST":
        sent = request.form.get("_csrf", "")
        if not secrets.compare_digest(session.get("_csrf", ""), sent):
            abort(400)


@app.after_request
def headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    return resp


@app.context_processor
def inject():
    session.setdefault("_csrf", secrets.token_hex(16))
    return dict(csrf=session["_csrf"], topics=TOPICS, topic_map=TOPIC_MAP,
                is_admin=session.get("admin", False))


def admin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrapper


ATTEMPTS = {}
def throttled(ip):
    now = time.time()
    ATTEMPTS[ip] = [t for t in ATTEMPTS.get(ip, []) if now - t < 600]
    return len(ATTEMPTS[ip]) >= 5


# ---------- public (read-only) ----------
@app.route("/")
def index():
    latest = Paper.query.order_by(Paper.uploaded_at.desc()).limit(6).all()
    return render_template("index.html", latest=latest)


@app.route("/topic/<slug>")
def topic(slug):
    t = TOPIC_MAP.get(slug) or abort(404)
    papers = Paper.query.filter_by(topic=slug).order_by(Paper.year.desc(), Paper.id.desc()).all()
    return render_template("list.html", heading=t["name"], sub=t["blurb"], papers=papers)


@app.route("/search")
def search():
    q = request.args.get("q", "").strip()[:100]
    papers = []
    if q:
        like = f"%{q}%"
        papers = Paper.query.filter(or_(Paper.title.ilike(like), Paper.authors.ilike(like),
                                        Paper.abstract.ilike(like), Paper.journal.ilike(like))).all()
    return render_template("list.html", heading=f"Results for “{q}”" if q else "Search",
                           sub=f"{len(papers)} found" if q else "Type a title, author or keyword.", papers=papers)


@app.route("/paper/<int:pid>")
def paper(pid):
    return render_template("paper.html", p=db.get_or_404(Paper, pid))


@app.route("/paper/<int:pid>/pdf")
def pdf(pid):
    p = db.get_or_404(Paper, pid)
    return send_from_directory(UPLOADS, p.filename, mimetype="application/pdf",
                               as_attachment=request.args.get("dl") == "1",
                               download_name=p.original_name)


# ---------- admin ----------
@app.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = request.remote_addr or "?"
        if ADMIN_HASH is None:
            flash("Admin login is disabled: set ADMIN_PASSWORD on the server.", "error")
        elif throttled(ip):
            flash("Too many attempts. Try again in 10 minutes.", "error")
        elif (request.form.get("username") == ADMIN_USER
              and check_password_hash(ADMIN_HASH, request.form.get("password", ""))):
            session.clear()
            session["admin"] = True
            return redirect(url_for("dashboard"))
        else:
            ATTEMPTS.setdefault(ip, []).append(time.time())
            flash("Wrong username or password.", "error")
    return render_template("login.html")


@app.route("/admin/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def dashboard():
    return render_template("admin.html", papers=Paper.query.order_by(Paper.uploaded_at.desc()).all())


@app.route("/admin/upload", methods=["POST"])
@admin_required
def upload():
    f = request.files.get("pdf")
    title = request.form.get("title", "").strip()
    topic_slug = request.form.get("topic", "")
    year = request.form.get("year", "").strip()
    if not title or topic_slug not in TOPIC_MAP or not f or not f.filename:
        flash("Add a title, choose a topic and select a PDF.", "error")
        return redirect(url_for("dashboard"))
    if f.read(5) != b"%PDF-":
        flash("That file is not a PDF.", "error")
        return redirect(url_for("dashboard"))
    f.seek(0)
    name = uuid.uuid4().hex + ".pdf"
    f.save(os.path.join(UPLOADS, name))
    db.session.add(Paper(
        title=title[:300], authors=request.form.get("authors", "").strip()[:400],
        journal=request.form.get("journal", "").strip()[:200],
        year=int(year) if year.isdigit() and 1800 < int(year) < 2100 else None,
        doi=request.form.get("doi", "").strip()[:200],
        abstract=request.form.get("abstract", "").strip(),
        topic=topic_slug, filename=name, original_name=os.path.basename(f.filename)[:200]))
    db.session.commit()
    flash("Paper published.", "ok")
    return redirect(url_for("dashboard"))


@app.route("/admin/delete/<int:pid>", methods=["POST"])
@admin_required
def delete(pid):
    p = db.get_or_404(Paper, pid)
    try:
        os.remove(os.path.join(UPLOADS, p.filename))
    except OSError:
        pass
    db.session.delete(p)
    db.session.commit()
    flash("Paper deleted.", "ok")
    return redirect(url_for("dashboard"))


@app.errorhandler(413)
def too_big(_):
    flash("PDF is larger than 25 MB.", "error")
    return redirect(url_for("dashboard" if session.get("admin") else "index"))


if __name__ == "__main__":
    app.run(debug=True)
