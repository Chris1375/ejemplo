"""Configuración de CafeterIA."""
import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Antes: SECRET_KEY estaba fija y subida al repositorio (OWASP A02). Con esa
# clave pública cualquiera puede FIRMAR sus propias cookies de sesión Flask
# (por ejemplo una con es_admin=True) sin pasar por /login. Ahora se toma de
# una variable de entorno y, si no existe (por ejemplo en desarrollo local),
# se genera una aleatoria al iniciar — ya no queda fija ni versionada.
SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

# Modo debug: antes quedaba en True por defecto. Con DEBUG=True, cualquier
# error no controlado muestra el depurador interactivo de Werkzeug, que
# permite ejecutar código Python desde el navegador (OWASP A02). Ahora se
# desactiva por defecto y solo se activa explícitamente con la variable de
# entorno FLASK_DEBUG=1 (útil mientras se desarrolla, nunca en producción).
DEBUG = os.environ.get("FLASK_DEBUG") == "1"

DATABASE = os.path.join(BASE_DIR, "cafeteria.db")
LOG_FILE = os.path.join(BASE_DIR, "cafeteria.log")

# Antes: SESSION_COOKIE_HTTPONLY = False permitía que JavaScript leyera la
# cookie de sesión — si en algún punto existe una inyección (XSS), bastaría
# con robar esa cookie para suplantar al usuario (OWASP A02). Ahora la cookie
# de sesión no es accesible desde JavaScript.
SESSION_COOKIE_HTTPONLY = True

# Pasarela de pagos CafePay
PASARELA_URL = "https://api.cafepay.example/v1"
PASARELA_API_KEY = os.environ.get("PASARELA_API_KEY", "")
