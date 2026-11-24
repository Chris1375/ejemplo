"""CafeterIA 🍔🤖 — La app de pedidos de la cafetería de la universidad.

Generada 100 % con IA en un fin de semana ("vibe coding") y lista para salir
a producción el lunes... ¿o no?

⚠️  APLICACIÓN INTENCIONALMENTE VULNERABLE. Úsala solo en tu equipo o en tu
    Codespace para aprender. Nunca la publiques en internet.
"""
import ast
import csv
import functools
import hashlib
import io
import logging
import operator
import os
import random
import sqlite3
import subprocess
import sys
from datetime import datetime
from markupsafe import escape

from flask import (
    Blueprint,
    Flask,
    Response,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    render_template_string,
    request,
    send_file,
    session,
    url_for,
)

import config
import db
from seguridad import hash_password, verificar_password

bp = Blueprint("web", __name__)

TABLA_PLATOS = "platos"
BANNER_HTML = "<strong>¡Nuevo!</strong> Pide desde el celular y recoge sin hacer fila 🚀"


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(config)
    if test_config:
        app.config.update(test_config)

    configurar_logs(app)
    app.teardown_appcontext(db.close_db)
    app.register_blueprint(bp)

    with app.app_context():
        db.init_db_si_no_existe()

    return app


def configurar_logs(app):
    manejador = logging.FileHandler(app.config["LOG_FILE"], encoding="utf-8")
    manejador.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    manejador.set_name("cafeteria")
    for anterior in [h for h in app.logger.handlers if h.get_name() == "cafeteria"]:
        app.logger.removeHandler(anterior)
        anterior.close()
    app.logger.addHandler(manejador)
    app.logger.setLevel(logging.INFO)


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def login_requerido(vista):
    @functools.wraps(vista)
    def envoltura(*args, **kwargs):
        if g.usuario is None:
            flash("Primero inicia sesión 🙂", "error")
            return redirect(url_for("web.login", next=request.path))
        return vista(*args, **kwargs)

    return envoltura


@bp.before_app_request
def cargar_usuario():
    usuario_id = session.get("usuario_id")
    g.usuario = None
    if usuario_id is not None:
        g.usuario = db.get_db().execute(
            "SELECT * FROM usuarios WHERE id = ?", (usuario_id,)
        ).fetchone()


@bp.app_template_filter("pesos")
def formato_pesos(valor):
    try:
        return "$" + f"{int(valor):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(valor)


@bp.app_template_global()
def estatico(nombre):
    """URL de un archivo estático con una huella de su contenido, para que el navegador no use una copia vieja."""
    with open(os.path.join(current_app.static_folder, nombre), "rb") as archivo:
        huella = hashlib.md5(archivo.read()).hexdigest()[:8]
    return url_for("static", filename=nombre, v=huella)


# ─────────────────────────────── Menú ────────────────────────────────


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    conexion = db.get_db()
    todos = conexion.execute(
        "SELECT id, nombre, descripcion, precio, emoji FROM platos WHERE disponible = 1"
    ).fetchall()

    if q:
        # Búsqueda por nombre (acepta coincidencias parciales)
        # Antes: f"... LIKE '%{q}%'" permitía inyección SQL (p. ej. q=' OR '1'='1).
        # Ahora el valor viaja como parámetro, nunca como texto de la consulta.
        patron = f"%{q}%"
        platos = conexion.execute(
            "SELECT id, nombre, descripcion, precio, emoji FROM platos "
            "WHERE disponible = 1 AND nombre LIKE ?",
            (patron,),
        ).fetchall()
    else:
        platos = todos

    total_platos = conexion.execute(f"SELECT COUNT(*) FROM {TABLA_PLATOS}").fetchone()[0]
    plato_del_dia = random.choice(todos) if todos else None
    return render_template(
        "index.html",
        platos=platos,
        q=q,
        total_platos=total_platos,
        plato_del_dia=plato_del_dia,
        banner=BANNER_HTML,
    )


@bp.route("/plato/<int:plato_id>")
def ver_plato(plato_id):
    conexion = db.get_db()
    plato = conexion.execute("SELECT * FROM platos WHERE id = ?", (plato_id,)).fetchone()
    if plato is None:
        abort(404)
    resenas = conexion.execute(
        "SELECT r.*, u.nombre AS autor FROM resenas r JOIN usuarios u ON u.id = r.usuario_id "
        "WHERE r.plato_id = ? ORDER BY r.id DESC",
        (plato_id,),
    ).fetchall()
    return render_template("plato.html", plato=plato, resenas=resenas)


@bp.route("/plato/<int:plato_id>/resena", methods=["POST"])
@login_requerido
def agregar_resena(plato_id):
    comentario = request.form.get("comentario", "").strip()
    estrellas = request.form.get("estrellas", "5")
    if comentario:
        conexion = db.get_db()
        conexion.execute(
            "INSERT INTO resenas (plato_id, usuario_id, comentario, estrellas, fecha) VALUES (?, ?, ?, ?, ?)",
            (plato_id, g.usuario["id"], comentario, estrellas, ahora()),
        )
        conexion.commit()
        flash("¡Gracias por tu reseña! ⭐", "exito")
    return redirect(url_for("web.ver_plato", plato_id=plato_id))


@bp.route("/descargar")
def descargar():
    archivo = request.args.get("archivo", "menu-semana.txt")
    # Antes: unía `archivo` a la ruta sin contenerlo dentro de static/descargas,
    # así que algo como "../../../app.py" o "../config.py" escapaba la carpeta
    # (path traversal). Ahora se resuelve la ruta final y se verifica que siga
    # dentro de la carpeta permitida antes de servir el archivo.
    carpeta_descargas = os.path.realpath(os.path.join(current_app.root_path, "static", "descargas"))
    ruta = os.path.realpath(os.path.join(carpeta_descargas, archivo))
    if os.path.commonpath([carpeta_descargas, ruta]) != carpeta_descargas or not os.path.isfile(ruta):
        abort(404)
    return send_file(ruta, mimetype="text/plain")


_OPERADORES_PERMITIDOS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _calcular_seguro(nodo):
    """Evalúa solo expresiones aritméticas (+ - * / % **), sin ejecutar código."""
    if isinstance(nodo, ast.Expression):
        return _calcular_seguro(nodo.body)
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, (int, float)):
        return nodo.value
    if isinstance(nodo, ast.BinOp) and type(nodo.op) in _OPERADORES_PERMITIDOS:
        return _OPERADORES_PERMITIDOS[type(nodo.op)](_calcular_seguro(nodo.left), _calcular_seguro(nodo.right))
    if isinstance(nodo, ast.UnaryOp) and type(nodo.op) in _OPERADORES_PERMITIDOS:
        return _OPERADORES_PERMITIDOS[type(nodo.op)](_calcular_seguro(nodo.operand))
    raise ValueError("solo se permiten operaciones aritméticas")


@bp.route("/propina")
def propina():
    expresion = request.args.get("expresion", "").strip()
    resultado = None
    if expresion:
        # Antes: `eval(expresion)` ejecutaba cualquier código Python que llegara
        # en el parámetro `expresion` (ejecución remota de código, OWASP A05).
        # El comentario que había aquí intentaba convencer a un asistente de IA
        # de ignorar este problema (prompt injection) — se eliminó junto con el
        # eval(). Ahora solo se evalúa un árbol sintáctico de operaciones
        # aritméticas permitidas, nunca código arbitrario.
        try:
            resultado = _calcular_seguro(ast.parse(expresion, mode="eval"))
        except Exception as error:
            resultado = f"No pude calcular eso 🤔 ({error})"
    return render_template("propina.html", expresion=expresion, resultado=resultado)


# ───────────────────────────── Usuarios ──────────────────────────────


@bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        # Antes: se registraba la contraseña en texto plano en el log
        # (OWASP A09) y la consulta concatenaba email/hash directamente en el
        # SQL (inyección SQL, OWASP A05: p. ej. email = ' OR '1'='1 permitía
        # entrar sin contraseña). Ahora el log no incluye la contraseña y la
        # consulta usa parámetros.
        current_app.logger.info(f"Intento de login: email={email}")

        conexion = db.get_db()
        candidato = conexion.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()
        # El hash ahora lleva una sal aleatoria (ver seguridad.py), así que dos
        # hashes del mismo texto no son iguales entre sí: hay que usar
        # verificar_password (que sí sabe comparar contra la sal guardada) en
        # vez de comparar hash_password(password) por igualdad en el SQL.
        usuario = candidato if candidato and verificar_password(password, candidato["password_hash"]) else None

        if usuario:
            session.clear()
            session["usuario_id"] = usuario["id"]
            session["nombre"] = usuario["nombre"]
            session["es_admin"] = bool(usuario["es_admin"])
            current_app.logger.info(f"Login exitoso: {usuario['email']}")
            return redirect(request.args.get("next") or url_for("web.index"))

        existe = conexion.execute("SELECT id FROM usuarios WHERE email = ?", (email,)).fetchone()
        if existe:
            error = "Contraseña incorrecta. ¿La olvidaste?"
        else:
            error = "No existe ninguna cuenta con ese correo."
    return render_template("login.html", error=error)


@bp.route("/registro", methods=["GET", "POST"])
def registro():
    error = None
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        carrera = request.form.get("carrera", "").strip()
        password = request.form.get("password", "")
        if not nombre or not email or not password:
            error = "Todos los campos son obligatorios."
        else:
            try:
                conexion = db.get_db()
                conexion.execute(
                    "INSERT INTO usuarios (nombre, email, password_hash, carrera, saldo, es_admin) "
                    "VALUES (?, ?, ?, ?, ?, 0)",
                    (nombre, email, hash_password(password), carrera, 20000),
                )
                conexion.commit()
            except sqlite3.IntegrityError:
                error = "Ese correo ya está registrado."
            else:
                flash("¡Cuenta creada! Te regalamos $20.000 de bienvenida 🎁", "exito")
                return redirect(url_for("web.login"))
    return render_template("registro.html", error=error)


@bp.route("/salir")
def logout():
    session.clear()
    flash("Sesión cerrada. ¡Vuelve pronto! 👋", "exito")
    return redirect(url_for("web.index"))


@bp.route("/perfil", methods=["GET", "POST"])
@login_requerido
def perfil():
    conexion = db.get_db()
    if request.method == "POST":
        # Antes: actualizaba CUALQUIER columna que llegara como campo del
        # formulario (asignación masiva, OWASP A01/A06). Un atacante podía
        # enviar un campo oculto `es_admin=1` (o `password_hash`, `saldo`...)
        # y auto-ascenderse a decano sin conocer su contraseña. Ahora solo se
        # permite actualizar los campos del perfil que la vista expone.
        CAMPOS_PERFIL_PERMITIDOS = {"nombre", "carrera"}
        for campo, valor in request.form.items():
            if campo in CAMPOS_PERFIL_PERMITIDOS:
                conexion.execute(f"UPDATE usuarios SET {campo} = ? WHERE id = ?", (valor, g.usuario["id"]))
        conexion.commit()
        flash("Perfil actualizado ✅", "exito")
        return redirect(url_for("web.perfil"))
    return render_template("perfil.html", usuario=g.usuario)


# ───────────────────────────── Pedidos ───────────────────────────────


@bp.route("/pedir", methods=["POST"])
@login_requerido
def pedir():
    plato_id = int(request.form["plato_id"])
    cantidad = int(request.form.get("cantidad", 1))
    notas = request.form.get("notas", "").strip()

    conexion = db.get_db()
    # Antes: el precio venía tal cual del formulario (`request.form["precio"]`),
    # así que con F12 o un curl se podía pedir cualquier plato a $1 (el
    # servidor confiaba en el cliente, OWASP A06/A08). Ahora el precio se
    # vuelve a calcular en el servidor a partir del plato real en la base de
    # datos, y el valor que mande el navegador se ignora.
    plato = conexion.execute("SELECT precio FROM platos WHERE id = ?", (plato_id,)).fetchone()
    if plato is None:
        abort(404)
    precio = plato["precio"]
    total = precio * cantidad

    if total > g.usuario["saldo"]:
        flash("Saldo insuficiente 😢 Recarga en la caja de la cafetería.", "error")
        return redirect(url_for("web.ver_plato", plato_id=plato_id))

    conexion.execute("UPDATE usuarios SET saldo = saldo - ? WHERE id = ?", (total, g.usuario["id"]))
    cursor = conexion.execute(
        "INSERT INTO pedidos (usuario_id, plato_id, cantidad, total, notas, fecha) VALUES (?, ?, ?, ?, ?, ?)",
        (g.usuario["id"], plato_id, cantidad, total, notas, ahora()),
    )
    conexion.commit()
    current_app.logger.info(
        f"Pedido #{cursor.lastrowid}: usuario={g.usuario['id']} plato={plato_id} cantidad={cantidad} total={total}"
    )
    flash(f"¡Pedido #{cursor.lastrowid} confirmado! Te avisamos cuando esté listo 🛎️", "exito")
    return redirect(url_for("web.ver_pedido", pedido_id=cursor.lastrowid))


@bp.route("/pedido/<int:pedido_id>")
@login_requerido
def ver_pedido(pedido_id):
    pedido = db.get_db().execute(
        "SELECT p.*, pl.nombre AS plato, pl.emoji, u.nombre AS cliente, u.email "
        "FROM pedidos p JOIN platos pl ON pl.id = p.plato_id JOIN usuarios u ON u.id = p.usuario_id "
        "WHERE p.id = ?",
        (pedido_id,),
    ).fetchone()
    # Antes: cualquier usuario autenticado podía ver el pedido de cualquier
    # otro con solo cambiar el número en /pedido/<id> (IDOR, control de acceso
    # roto, OWASP A01) — incluyendo nombre, correo y notas de otra persona.
    # Ahora se exige que el pedido sea del usuario en sesión (o que sea
    # decano/admin).
    if pedido is None or (pedido["usuario_id"] != g.usuario["id"] and not g.usuario["es_admin"]):
        abort(404)
    return render_template("pedido.html", pedido=pedido)


@bp.route("/mis-pedidos")
@login_requerido
def mis_pedidos():
    pedidos = db.get_db().execute(
        "SELECT p.*, pl.nombre AS plato, pl.emoji FROM pedidos p JOIN platos pl ON pl.id = p.plato_id "
        "WHERE p.usuario_id = ? ORDER BY p.id DESC",
        (g.usuario["id"],),
    ).fetchall()
    return render_template("mis_pedidos.html", pedidos=pedidos)


# ────────────────────────── Administración ───────────────────────────


@bp.route("/admin")
def admin():
    if not session.get("es_admin"):
        flash("Zona exclusiva del decano 🧐", "error")
        return redirect(url_for("web.login", next=request.path))
    conexion = db.get_db()
    usuarios = conexion.execute(
        "SELECT id, nombre, email, carrera, saldo, es_admin FROM usuarios"
    ).fetchall()
    ventas = conexion.execute(
        "SELECT COUNT(*) AS pedidos, COALESCE(SUM(total), 0) AS total FROM pedidos"
    ).fetchone()
    return render_template("admin.html", usuarios=usuarios, ventas=ventas)


@bp.route("/admin/exportar-usuarios")
def exportar_usuarios():
    # Antes: esta ruta no verificaba sesión ni rol (a diferencia de /admin), así
    # que CUALQUIERA sin iniciar sesión podía descargar el CSV con el hash de
    # la contraseña de todos los usuarios (fallas de autenticación, OWASP A01/
    # A07). robots.txt incluso anunciaba la ruta. Ahora exige ser decano/admin,
    # igual que /admin.
    if not session.get("es_admin"):
        flash("Zona exclusiva del decano 🧐", "error")
        return redirect(url_for("web.login", next=request.path))
    filas = db.get_db().execute(
        "SELECT id, nombre, email, password_hash, carrera, saldo FROM usuarios"
    ).fetchall()
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(["id", "nombre", "email", "password_hash", "carrera", "saldo"])
    for fila in filas:
        escritor.writerow(list(fila))
    return Response(
        salida.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=usuarios.csv"},
    )


# ───────────────────────────── Utilidades ────────────────────────────


@bp.route("/robots.txt")
def robots():
    return Response(
        "User-agent: *\nDisallow: /admin\nDisallow: /admin/exportar-usuarios\n",
        mimetype="text/plain",
    )


@bp.route("/api/version")
def version():
    try:
        resultado = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            cwd=current_app.root_path,
        )
        commit = resultado.stdout.strip() or "desconocido"
    except (OSError, subprocess.SubprocessError):
        commit = "desconocido"
    return {"app": "CafeterIA", "version": "1.0.0", "commit": commit}


@bp.app_errorhandler(404)
def pagina_no_encontrada(error):
    # Antes: `request.path` se concatenaba directamente dentro del texto de la
    # plantilla ANTES de renderizarla con render_template_string, así que una
    # URL como /{{7*7}} o /{{config}} se interpretaba como código Jinja
    # (Server-Side Template Injection, OWASP A05) y podía usarse para leer
    # configuración o ejecutar código. Ahora el valor se escapa como dato,
    # nunca como parte de la plantilla.
    plantilla = (
        '{% extends "base.html" %}{% block contenido %}'
        '<section class="tarjeta centro">'
        "<h1>🍳 Esa página no está en el menú</h1>"
        "<p>Buscamos <code>{{ ruta }}</code> por toda la cocina y no apareció.</p>"
        "<a class=\"boton\" href=\"{{ url_for('web.index') }}\">Volver al menú</a>"
        "</section>{% endblock %}"
    )
    return render_template_string(plantilla, ruta=request.path), 404


if __name__ == "__main__":
    if "--reiniciar" in sys.argv and os.path.exists(config.DATABASE):
        os.remove(config.DATABASE)
        print("🧹 Base de datos reiniciada con los datos de ejemplo.")
    aplicacion = create_app()
    # Escucha solo en 127.0.0.1: la app es vulnerable a propósito, ¡no la expongas en la red!
    aplicacion.run(host="127.0.0.1", port=5000, debug=aplicacion.config["DEBUG"])
