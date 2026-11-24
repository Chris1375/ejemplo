"""Utilidades de seguridad de CafeterIA 🔒"""
# Antes: MD5 sin sal (OWASP A04, fallas criptográficas). MD5 es rapidísimo de
# fuerza-bruta/rainbow-table y, sin sal, dos usuarios con la misma contraseña
# quedan con el MISMO hash (visible en el CSV de /admin/exportar-usuarios).
# Ahora se usa PBKDF2 con sal aleatoria por contraseña (vía werkzeug, que ya
# es una dependencia del proyecto), con comparación en tiempo constante.
from werkzeug.security import check_password_hash, generate_password_hash


def hash_password(password):
    """Devuelve el hash salado de la contraseña para no guardarla en texto plano."""
    return generate_password_hash(password)


def verificar_password(password, password_hash):
    """Compara una contraseña con el hash guardado en la base de datos."""
    return check_password_hash(password_hash, password)
