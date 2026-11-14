# Sistema de Ventas

Sistema web de ventas para pequeños negocios: restaurantes, tiendas de ropa, librerías y útiles, peluquerías, bodegas, etc.
Responsivo y se puede instalar en el celular como app (PWA).

**Tecnologías:** Django 5.2 · AdminLTE 4 (Bootstrap 5) · HTMX · SQLite (desarrollo) / PostgreSQL (producción)

---

## Instalación en Windows (desarrollo)

Requisito: **Python 3.10 o superior** (marca "Add Python to PATH" al instalarlo).

Abre una terminal (PowerShell o CMD) en la carpeta del proyecto:

```powershell
cd "C:\proyectos\sist-vent"

# 1. Crear y activar el entorno virtual
python -m venv .venv
.venv\Scripts\activate

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configuración: si no existe el archivo .env, créalo a partir del ejemplo
copy .env.example .env
#    (y cambia SECRET_KEY por una clave nueva)

# 4. Crear la base de datos y el usuario administrador
python manage.py migrate
python manage.py createsuperuser

# 5. Levantar el servidor
python manage.py runserver
```

Abre http://127.0.0.1:8000 e ingresa con el usuario que creaste.

> Si PowerShell no deja activar el entorno, ejecuta una vez:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### Probar desde el celular (misma red WiFi)

1. Averigua la IP de tu PC con `ipconfig` (por ejemplo `192.168.1.50`).
2. Agrégala en `.env`: `ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.50`
3. Levanta el servidor así: `python manage.py runserver 0.0.0.0:8000`
4. En el celular abre `http://192.168.1.50:8000`

> La opción **"Instalar app"** solo aparece con HTTPS (o en `localhost`).
> En la red local se ve y se usa igual, pero la instalación se probará cuando esté publicado con HTTPS.

---

## Estructura

Ver [ARQUITECTURA.md](ARQUITECTURA.md).

## Avance

- [x] **Base** – Login con bloqueo, usuarios, roles y permisos, módulos activables, datos del negocio (rubro, logo, RUC), PWA instalable
- [x] **Productos** – Productos y servicios, categorías, variantes (talla, color, tamaño), códigos de barras, stock con kardex, importar y exportar Excel
- [x] **Punto de venta** – Venta rápida con lectora de códigos, variantes, cobro en efectivo con vuelto, Yape, Plin, tarjeta o mixto, ticket 80 mm y WhatsApp, ventas del día por método, anulaciones
- [ ] Caja (apertura, cierre, ingresos y egresos)
- [ ] Clientes
- [ ] Reportes
- [ ] Despliegue con HTTPS

## Ver el sistema con datos de ejemplo

Doble clic en `demo.bat`. Crea una base aparte, `db_demo.sqlite3`, con un negocio de ejemplo (bodega). Para otro rubro: `python manage.py datos_demo --rubro ROP` (ROP ropa, RES restaurante, LIB librería, PEL peluquería) sobre una base vacía. **Tu base real (`db.sqlite3`) no se toca.**

Usuarios (clave `demo1234`): `admin` (administrador principal: módulos del sistema), `gerente` (Administración), `cajero`, `vendedor`.
Para regenerar los datos: `demo.bat nuevo`.
