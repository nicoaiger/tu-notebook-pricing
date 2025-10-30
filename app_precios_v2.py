
from __future__ import annotations
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, List, Tuple

from flask import Flask, g, render_template_string, request, redirect, url_for, flash

# ==============================
# App Config
# ==============================
APP_TITLE = "TuNotebook Pricing"
DB_PATH = os.path.join(os.path.dirname(__file__), "pricing.db")
SECRET_KEY = "dev-secret"  # cambia esto en producción

app = Flask(__name__)
app.secret_key = SECRET_KEY

from functools import wraps
from flask import session

# ==============================
# Autenticación simple
# ==============================
USERS = {
    "nico": "vindur2025",
    "adrian": "admin4050",
    # Podés agregar más usuarios así: "usuario": "contraseña"
}

def login_required(view_func):
    """Decorator para proteger rutas internas"""
    @wraps(view_func)
    def wrapped_view(**kwargs):
        if "user" not in session:
            flash("Iniciá sesión para acceder.")
            return redirect(url_for("login"))
        return view_func(**kwargs)
    return wrapped_view


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "").strip()
        if USERS.get(username) == password:
            session["user"] = username
            flash(f"Bienvenido, {username}.")
            return redirect(url_for("home"))
        else:
            flash("Usuario o contraseña incorrectos.")
            return redirect(url_for("login"))

    body = r"""
    <div class="max-w-sm mx-auto mt-10 p-6 bg-white rounded shadow">
      <h1 class="text-xl font-semibold mb-3 text-center">Iniciar sesión</h1>
      <form method="post" class="grid gap-3">
        <input name="username" placeholder="Usuario" class="border p-2 rounded" />
        <input name="password" type="password" placeholder="Contraseña" class="border p-2 rounded" />
        <button class="px-3 py-2 bg-slate-900 text-white rounded">Entrar</button>
      </form>
    </div>
    """
    return page(body, title="Login | " + APP_TITLE)


@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Sesión cerrada correctamente.")
    return redirect(url_for("login"))

# ==============================
# Force HTTPS redirect
# ==============================
@app.before_request
def enforce_https():
    # Solo aplicar en entorno de producción
    if request.headers.get("X-Forwarded-Proto", "http") != "https":
        url = request.url.replace("http://", "https://", 1)
        return redirect(url, code=301)

# ==============================
# Templating (Tailwind minimal)
# ==============================
BASE_HTML = r"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{{ title }}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    code { background: #f1f5f9; padding: 2px 6px; border-radius: 6px; }
    .money { font-variant-numeric: tabular-nums; }
  </style>
</head>
<body class="bg-slate-50 text-slate-900">
  <nav class="bg-white shadow sticky top-0 z-10">
    <div class="max-w-7xl mx-auto px-4 py-3 flex gap-4 items-center">
      <div class="font-bold">{{ app_title }}</div>
      <a href="{{ url_for('home') }}" class="hover:underline">Productos</a>
      <a href="{{ url_for('variables') }}" class="hover:underline">Variables</a>
      <a href="{{ url_for('about') }}" class="hover:underline">Ayuda</a>
    </div>
  </nav>
  <main class="max-w-7xl mx-auto p-4">
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <div class="mb-4">
          {% for m in messages %}
          <div class="p-3 bg-emerald-50 border border-emerald-200 rounded mb-2">{{ m }}</div>
          {% endfor %}
        </div>
      {% endif %}
    {% endwith %}
    {{ body|safe }}
  </main>
</body>
</html>
"""

def page(body: str, title: str):
    return render_template_string(BASE_HTML, body=body, title=title, app_title=APP_TITLE)

# ==============================
# DB Helpers
# ==============================
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    with closing(db.cursor()) as cur:
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS variables (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS products (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              brand TEXT NOT NULL,
              name TEXT NOT NULL,
              sku TEXT NOT NULL UNIQUE,
              weight_kg REAL NOT NULL DEFAULT 0,
              fob_usd REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS price_history (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              product_id INTEGER NOT NULL,
              price_web_ars REAL NOT NULL,
              price_ml1_ars REAL NOT NULL,
              price_ml3_ars REAL NOT NULL,
              price_ml6_ars REAL NOT NULL,
              price_ml9_ars REAL NOT NULL,
              price_ml12_ars REAL NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
            );
            """
        )
        db.commit()

    # Seed default variables if empty
    if not get_variables():
        seed = {
            # Cotización & importación
            "dolar": "1480",
            "costo_financiero": "0.04",
            "costo_flete": "4.20",
            "arancel": "0.16",
            "aduana": "0.0053",
            "despachante": "0.0095",
            "banco": "0.0040",
            # Comercial
            "margen_neto": "0.06",
            # Coeficientes ML
            "coef_ml_1": "1.1467",
            "coef_ml_3": "1.2698",
            "coef_ml_6": "1.4334",
            "coef_ml_9": "1.6208",
            "coef_ml_12": "1.8330",
            # Envíos (opcional) en ARS: suman al final si >0
            "envio_web": "0",
            "envio_ml": "0"
        }
        save_variables(seed)

def get_variables() -> Dict[str, float]:
    db = get_db()
    cur = db.execute("SELECT key, value FROM variables")
    out = {}
    for r in cur.fetchall():
        try:
            out[r["key"]] = float(r["value"])
        except ValueError:
            out[r["key"]] = 0.0
    return out

def save_variables(dct: Dict[str, Any]):
    db = get_db()
    with closing(db.cursor()) as cur:
        for k, v in dct.items():
            cur.execute(
                "INSERT INTO variables(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, str(v)),
            )
        db.commit()

# ==============================
# Domain Logic
# ==============================
def money(n: float) -> str:
    # format currency with thousands separator and no decimals
    return f"${int(round(n)):,.0f}".replace(",", ".")

def end_599_999(value: float) -> float:
    """
    Redondea a la terminación más cercana en 599 o 999.
    Estrategia: calculamos candidatos alrededor del valor y elegimos el más cercano.
    En caso de empate, preferimos 999.
    """
    base = int(value)
    thousands = base // 1000
    candidates = [
        thousands * 1000 + 599,
        thousands * 1000 + 999,
        (thousands + 1) * 1000 + 599,
        (thousands + 1) * 1000 + 999,
        max(0, (thousands - 1) * 1000 + 999),  # por si value < x599 del mismo mil
        max(0, (thousands - 1) * 1000 + 599),
    ]
    # quitar duplicados y no-negativos
    candidates = sorted(set([c for c in candidates if c >= 0]))
    # elegir por distancia; si empata, preferir 999
    best = None
    best_dist = None
    for c in candidates:
        dist = abs(c - value)
        if best is None or dist < best_dist or (dist == best_dist and c % 1000 == 999):
            best = c
            best_dist = dist
    return float(best if best is not None else value)

@dataclass
class CalcResult:
    cif_usd: float
    costo_usd: float
    pv_neto_usd: float
    precio_web_ars: float
    precio_ml_1_ars: float
    precio_ml_3_ars: float
    precio_ml_6_ars: float
    precio_ml_9_ars: float
    precio_ml_12_ars: float

def calculate_prices(vars: Dict[str, float], fob_usd: float, weight_kg: float) -> CalcResult:
    """
    Aplica las fórmulas definidas por el usuario:
    CIF = (FOB + FOB*costo_financiero) + (costo_flete * peso)
    Costo USD = CIF * (1 + (arancel + aduana + despachante + banco))
    PV Neto USD = Costo USD * (1 + margen_neto)
    Luego en ARS con dólar y coeficientes ML. Suma envío si está definido (>0).
    Finalmente se redondea a terminaciones 599/999.
    """
    dolar = vars.get("dolar", 1.0)
    costo_financiero = vars.get("costo_financiero", 0.0)
    costo_flete = vars.get("costo_flete", 0.0)
    arancel = vars.get("arancel", 0.0)
    aduana = vars.get("aduana", 0.0)
    despachante = vars.get("despachante", 0.0)
    banco = vars.get("banco", 0.0)
    margen_neto = vars.get("margen_neto", 0.0)

    coef_ml_1 = vars.get("coef_ml_1", 1.0)
    coef_ml_3 = vars.get("coef_ml_3", 1.0)
    coef_ml_6 = vars.get("coef_ml_6", 1.0)
    coef_ml_9 = vars.get("coef_ml_9", 1.0)
    coef_ml_12 = vars.get("coef_ml_12", 1.0)

    envio_web = vars.get("envio_web", 0.0)
    envio_ml = vars.get("envio_ml", 0.0)

    cif_usd = (fob_usd + (fob_usd * costo_financiero)) + (costo_flete * weight_kg)
    tasa_total = arancel + aduana + despachante + banco
    costo_usd = cif_usd * (1 + tasa_total)
    pv_neto_usd = costo_usd * (1 + margen_neto)

    # precios en ARS
    web_raw = pv_neto_usd * dolar + envio_web
    ml1_raw = pv_neto_usd * dolar * coef_ml_1 + envio_ml
    ml3_raw = pv_neto_usd * dolar * coef_ml_3 + envio_ml
    ml6_raw = pv_neto_usd * dolar * coef_ml_6 + envio_ml
    ml9_raw = pv_neto_usd * dolar * coef_ml_9 + envio_ml
    ml12_raw = pv_neto_usd * dolar * coef_ml_12 + envio_ml

    # aplicar terminaciones 599/999
    web = end_599_999(web_raw)
    ml1 = end_599_999(ml1_raw)
    ml3 = end_599_999(ml3_raw)
    ml6 = end_599_999(ml6_raw)
    ml9 = end_599_999(ml9_raw)
    ml12 = end_599_999(ml12_raw)

    return CalcResult(
        cif_usd=cif_usd,
        costo_usd=costo_usd,
        pv_neto_usd=pv_neto_usd,
        precio_web_ars=web,
        precio_ml_1_ars=ml1,
        precio_ml_3_ars=ml3,
        precio_ml_6_ars=ml6,
        precio_ml_9_ars=ml9,
        precio_ml_12_ars=ml12,
    )

# ==============================
# Routes
# ==============================
@app.route("/")
@login_required
def home():
    init_db()
    db = get_db()
    q = (request.args.get("q") or "").strip().lower()
    vars_map = get_variables()
    products = db.execute("SELECT * FROM products ORDER BY brand, name").fetchall()

    rows = []
    for p in products:
        calc = calculate_prices(vars_map, p["fob_usd"], p["weight_kg"])
        rows.append((p, calc))

    if q:
        rows = [r for r in rows if q in r[0]["name"].lower() or q in r[0]["sku"].lower() or q in r[0]["brand"].lower()]

    body = render_template_string(
        r"""
        <div class="flex items-center justify-between mb-4">
          <form method="get">
            <input name="q" value="{{ q }}" placeholder="Buscar por marca, modelo o SKU" class="border p-2 rounded w-72" />
          </form>
          <div class="flex gap-2">
            <a href="{{ url_for('recalc_all') }}" class="px-3 py-2 bg-emerald-700 text-white rounded">Recalcular todo</a>
            <a href="{{ url_for('new_product') }}" class="px-3 py-2 bg-slate-900 text-white rounded">+ Nuevo producto</a>
          </div>
        </div>

        <div class="overflow-x-auto">
        <table class="min-w-full bg-white rounded shadow">
          <thead class="bg-slate-100 text-left text-sm">
            <tr>
              <th class="p-2">Marca</th>
              <th class="p-2">Producto</th>
              <th class="p-2">SKU</th>
              <th class="p-2 text-right">FOB (USD)</th>
              <th class="p-2 text-right">Peso (Kg)</th>
              <th class="p-2 text-right">Costo USD</th>
              <th class="p-2 text-right">PV Neto USD</th>
              <th class="p-2 text-right">Web (ARS)</th>
              <th class="p-2 text-right">ML 1</th>
              <th class="p-2 text-right">ML 3</th>
              <th class="p-2 text-right">ML 6</th>
              <th class="p-2 text-right">ML 9</th>
              <th class="p-2 text-right">ML 12</th>
              <th class="p-2"></th>
            </tr>
          </thead>
          <tbody class="text-sm">
            {% for p, c in rows %}
            <tr class="border-t">
              <td class="p-2">{{ p['brand'] }}</td>
              <td class="p-2">{{ p['name'] }}</td>
              <td class="p-2 font-mono">{{ p['sku'] }}</td>
              <td class="p-2 text-right">{{ '%.2f' % p['fob_usd'] }}</td>
              <td class="p-2 text-right">{{ '%.2f' % p['weight_kg'] }}</td>
              <td class="p-2 text-right">{{ '%.2f' % c.costo_usd }}</td>
              <td class="p-2 text-right">{{ '%.2f' % c.pv_neto_usd }}</td>
              <td class="p-2 text-right money">{{ money(c.precio_web_ars) }}</td>
              <td class="p-2 text-right money">{{ money(c.precio_ml_1_ars) }}</td>
              <td class="p-2 text-right money">{{ money(c.precio_ml_3_ars) }}</td>
              <td class="p-2 text-right money">{{ money(c.precio_ml_6_ars) }}</td>
              <td class="p-2 text-right money">{{ money(c.precio_ml_9_ars) }}</td>
              <td class="p-2 text-right money">{{ money(c.precio_ml_12_ars) }}</td>
              <td class="p-2 text-right">
                <a href="{{ url_for('edit_product', pid=p['id']) }}" class="text-blue-700">Editar</a>
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
        </div>
        """,
        rows=rows, q=q, money=money,
    )
    return page(body, title="Productos | " + APP_TITLE)

@app.route("/about")
def about():
    init_db()
    vars_map = get_variables()
    body = render_template_string(
        r"""
        <h1 class="text-xl font-semibold mb-3">Ayuda rápida</h1>
        <ol class="list-decimal ml-6 space-y-1">
          <li>Primero, cargá o ajustá las <a href="{{ url_for('variables') }}" class="text-blue-700 underline">Variables</a> (dólar, costos, coeficientes).</li>
          <li>Luego agregá tus productos con <strong>Marca, Modelo, SKU, Peso y FOB (USD)</strong>.</li>
          <li>La tabla de Productos calcula automáticamente CIF, Costo USD, PV Neto USD y precios ARS para Web y ML (1-12 cuotas), redondeados a 599/999.</li>
        </ol>
        <h2 class="text-lg font-semibold mt-6 mb-2">Fórmulas</h2>
        <pre class="p-3 bg-white rounded border text-sm overflow-x-auto">
CIF = (FOB + (FOB * costo_financiero)) + (costo_flete * peso)
Costo USD = CIF * (1 + (arancel + aduana + despachante + banco))
PV Neto USD = Costo USD * (1 + margen_neto)

Precio Web (ARS) = redondear_599_999( PV Neto USD * dolar + envio_web )
Precio ML (ARS)  = redondear_599_999( PV Neto USD * dolar * coef_ml_X + envio_ml )
        </pre>
        <h2 class="text-lg font-semibold mt-6 mb-2">Variables actuales</h2>
        <div class="grid grid-cols-2 md:grid-cols-3 gap-2 text-sm">
          {% for k, v in vars_map.items() %}
          <div class="p-2 bg-white rounded border"><strong>{{ k }}</strong>: {{ v }}</div>
          {% endfor %}
        </div>
        """,
        vars_map=vars_map,
    )
    return page(body, title="Ayuda | " + APP_TITLE)

@app.route("/variables", methods=["GET", "POST"])
@login_required
def variables():
    init_db()
    if request.method == "POST":
        # Guardar cada campo enviado
        payload = dict(request.form)
        # normalizar decimales con coma
        for k, v in payload.items():
            payload[k] = v.replace(",", ".").strip()
        save_variables(payload)
        flash("Variables actualizadas.")
        return redirect(url_for("variables"))

    vars_map = get_variables()
    # Orden prolijo por secciones
    order = [
        ("dolar", "Dólar (ARS por USD)"),
        ("costo_financiero", "% Financiero (decimal, ej. 0.04)"),
        ("costo_flete", "Flete USD/kg (ej. 4.20)"),
        ("arancel", "Arancel (decimal)"),
        ("aduana", "Aduana (decimal)"),
        ("despachante", "Despachante (decimal)"),
        ("banco", "Banco (decimal)"),
        ("margen_neto", "Margen neto (decimal)"),
        ("coef_ml_1", "Coef ML 1 cuota"),
        ("coef_ml_3", "Coef ML 3 cuotas"),
        ("coef_ml_6", "Coef ML 6 cuotas"),
        ("coef_ml_9", "Coef ML 9 cuotas"),
        ("coef_ml_12", "Coef ML 12 cuotas"),
        ("envio_web", "Envío WEB (ARS, opcional)"),
        ("envio_ml", "Envío ML (ARS, opcional)"),
    ]

    # Construir form
    body = render_template_string(
        r"""
        <h1 class="text-xl font-semibold mb-3">Variables globales</h1>
        <form method="post" class="grid gap-3 max-w-3xl">
          <div class="grid md:grid-cols-2 gap-2">
            {% for key, label in order %}
            <label class="flex items-center justify-between gap-2 bg-white p-2 rounded border">
              <span class="text-sm">{{ label }}</span>
              <input name="{{ key }}" value="{{ '%.6f' % vars_map.get(key, 0.0) }}" class="border p-1 rounded w-40 text-right" />
            </label>
            {% endfor %}
          </div>
          <div>
            <button class="px-3 py-2 bg-slate-900 text-white rounded">Guardar</button>
          </div>
        </form>
        """,
        vars_map=vars_map, order=order,
    )
    return page(body, title="Variables | " + APP_TITLE)

@app.route("/product/new", methods=["GET", "POST"])
@login_required
def new_product():
    init_db()
    if request.method == "POST":
        brand = (request.form.get("brand") or "").strip()
        name = (request.form.get("name") or "").strip()
        sku = (request.form.get("sku") or "").strip()
        weight = (request.form.get("weight_kg") or "0").replace(",", ".")
        fob = (request.form.get("fob_usd") or "0").replace(",", ".")
        try:
            weight = float(weight)
            fob = float(fob)
        except ValueError:
            flash("Datos numéricos inválidos.")
            return redirect(url_for("new_product"))
        if not (brand and name and sku):
            flash("Marca, Producto y SKU son obligatorios.")
            return redirect(url_for("new_product"))
        db = get_db()
        try:
            db.execute(
                "INSERT INTO products(brand, name, sku, weight_kg, fob_usd) VALUES (?, ?, ?, ?, ?)",
                (brand, name, sku, weight, fob),
            )
            db.commit()
            flash("Producto creado.")
            pid = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            return redirect(url_for("edit_product", pid=pid))
        except sqlite3.IntegrityError:
            flash("Ese SKU ya existe.")
            return redirect(url_for("new_product"))

    body = r"""
    <h1 class="text-xl font-semibold mb-3">Nuevo producto</h1>
    <form method="post" class="grid gap-3 max-w-xl">
      <input name="brand" placeholder="Marca" class="border p-2 rounded" />
      <input name="name" placeholder="Nombre / Modelo" class="border p-2 rounded" />
      <input name="sku" placeholder="SKU" class="border p-2 rounded" />
      <div class="grid grid-cols-2 gap-2">
        <input name="weight_kg" placeholder="Peso (kg)" class="border p-2 rounded" />
        <input name="fob_usd" placeholder="FOB (USD)" class="border p-2 rounded" />
      </div>
      <button class="px-3 py-2 bg-slate-900 text-white rounded">Guardar</button>
    </form>
    """
    return page(body, title="Nuevo producto | " + APP_TITLE)

@app.route("/product/<int:pid>", methods=["GET", "POST"])
@login_required
def edit_product(pid: int):
    init_db()
    db = get_db()
    p = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if not p:
        flash("Producto no encontrado.")
        return redirect(url_for("home"))

    if request.method == "POST":
        brand = (request.form.get("brand") or p["brand"]).strip()
        name = (request.form.get("name") or p["name"]).strip()
        sku = (request.form.get("sku") or p["sku"]).strip()
        weight = (request.form.get("weight_kg") or str(p["weight_kg"])).replace(",", ".")
        fob = (request.form.get("fob_usd") or str(p["fob_usd"])).replace(",", ".")
        try:
            weight = float(weight)
            fob = float(fob)
        except ValueError:
            flash("Datos numéricos inválidos.")
            return redirect(url_for("edit_product", pid=pid))
        try:
            db.execute(
                "UPDATE products SET brand=?, name=?, sku=?, weight_kg=?, fob_usd=? WHERE id=?",
                (brand, name, sku, weight, fob, pid),
            )
            db.commit()
            flash("Producto actualizado.")
            return redirect(url_for("edit_product", pid=pid))
        except sqlite3.IntegrityError:
            flash("Ese SKU ya existe.")
            return redirect(url_for("edit_product", pid=pid))

    vars_map = get_variables()
    calc = calculate_prices(vars_map, p["fob_usd"], p["weight_kg"])

    body = render_template_string(
        r"""
        <h1 class="text-xl font-semibold mb-3">Editar producto</h1>
        <form method="post" class="grid gap-3 max-w-xl mb-6">
          <input name="brand" value="{{ p['brand'] }}" class="border p-2 rounded" />
          <input name="name" value="{{ p['name'] }}" class="border p-2 rounded" />
          <input name="sku" value="{{ p['sku'] }}" class="border p-2 rounded" />
          <div class="grid grid-cols-2 gap-2">
            <input name="weight_kg" value="{{ '%.3f' % p['weight_kg'] }}" class="border p-2 rounded" />
            <input name="fob_usd" value="{{ '%.2f' % p['fob_usd'] }}" class="border p-2 rounded" />
          </div>
          <button class="px-3 py-2 bg-slate-900 text-white rounded">Guardar</button>
        </form>

        <div class="grid md:grid-cols-2 gap-4">
          <div class="p-4 bg-white rounded border">
            <h2 class="font-semibold mb-2">Resumen de cálculo</h2>
            <div class="text-sm space-y-1">
              <div>CIF (USD): <strong>{{ '%.2f' % calc.cif_usd }}</strong></div>
              <div>Costo USD: <strong>{{ '%.2f' % calc.costo_usd }}</strong></div>
              <div>PV Neto USD: <strong>{{ '%.2f' % calc.pv_neto_usd }}</strong></div>
            </div>
          </div>
          <div class="p-4 bg-white rounded border">
            <h2 class="font-semibold mb-2">Precios sugeridos</h2>
            <div class="grid grid-cols-2 gap-2 text-sm">
              <div>Web (ARS)</div><div class="text-right money"><strong>{{ money(calc.precio_web_ars) }}</strong></div>
              <div>ML 1</div><div class="text-right money"><strong>{{ money(calc.precio_ml_1_ars) }}</strong></div>
              <div>ML 3</div><div class="text-right money"><strong>{{ money(calc.precio_ml_3_ars) }}</strong></div>
              <div>ML 6</div><div class="text-right money"><strong>{{ money(calc.precio_ml_6_ars) }}</strong></div>
              <div>ML 9</div><div class="text-right money"><strong>{{ money(calc.precio_ml_9_ars) }}</strong></div>
              <div>ML 12</div><div class="text-right money"><strong>{{ money(calc.precio_ml_12_ars) }}</strong></div>
            </div>
          </div>
        </div>
        """,
        p=p, calc=calc, money=money,
    )
    return page(body, title=f"Editar {p['sku']} | " + APP_TITLE)

@app.route("/recalc-all")
@login_required
def recalc_all():
    init_db()
    db = get_db()
    vars_map = get_variables()
    products = db.execute("SELECT * FROM products").fetchall()
    for p in products:
        c = calculate_prices(vars_map, p["fob_usd"], p["weight_kg"])
        db.execute(
            """
            INSERT INTO price_history(product_id, price_web_ars, price_ml1_ars, price_ml3_ars, price_ml6_ars, price_ml9_ars, price_ml12_ars, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p["id"], c.precio_web_ars, c.precio_ml_1_ars, c.precio_ml_3_ars, c.precio_ml_6_ars, c.precio_ml_9_ars, c.precio_ml_12_ars,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    db.commit()
    flash("Recalculado y guardado en historial para todos los productos.")
    return redirect(url_for("home"))

@app.route("/product/<int:pid>/delete")
def delete_product(pid: int):
    init_db()
    db = get_db()
    db.execute("DELETE FROM products WHERE id=?", (pid,))
    db.commit()
    flash("Producto eliminado.")
    return redirect(url_for("home"))

# alias legible
recalc_all.methods = ["GET"]
home.methods = ["GET"]
about.methods = ["GET"]
variables.methods = ["GET", "POST"]

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
