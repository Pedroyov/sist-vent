# Sistema de Gestión Escolar

Sistema web para la gestión interna del colegio: alumnos, cobranza, asistencia y notas.
Responsivo y se puede instalar en el celular como app (PWA).

**Tecnologías:** Django 5.2 · AdminLTE 4 (Bootstrap 5) · HTMX · SQLite (desarrollo) / PostgreSQL (producción)

---

## Instalación en Windows (desarrollo)

Requisito: **Python 3.10 o superior** (marca "Add Python to PATH" al instalarlo).

Abre una terminal (PowerShell o CMD) en la carpeta del proyecto:

```powershell
cd "C:\proyectos\sist gestion"

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

```
sist gestion/
├── config/            # Configuración del proyecto (settings, urls)
├── core/              # Inicio, login y PWA (manifest, service worker)
├── templates/
│   ├── base.html      # Plantilla principal (AdminLTE)
│   ├── partials/      # Menú lateral, barra superior, mensajes
│   ├── registration/  # Login
│   └── core/          # Inicio, offline, service worker
├── static/
│   ├── css/app.css    # Estilos propios
│   ├── js/app.js      # JS propio (PWA, tema oscuro)
│   ├── img/icons/     # Íconos de la app
│   └── vendor/        # AdminLTE, Bootstrap, Bootstrap Icons, HTMX (locales)
├── manage.py
├── requirements.txt
└── .env.example
```

## Avance

- [x] **Paso 0** – Proyecto base, configuración con `.env`
- [x] **Paso 1** – Plantilla AdminLTE responsiva, login, inicio, PWA instalable
- [ ] **Paso 2** – `core`: año lectivo, niveles, grados, secciones, roles
- [ ] **Paso 3** – `alumnos`: alumnos, apoderados, matrícula, importar Excel
- [ ] **Paso 4** – `cobranza`: cronograma, pagos, recibos, morosos
- [ ] **Paso 5** – `asistencia`
- [ ] **Paso 6** – `notas` y libretas
- [ ] **Paso 7** – Despliegue con HTTPS

## Ver el sistema con datos de ejemplo

Doble clic en `demo.bat` (o ejecútalo desde la terminal). Crea una base aparte, `db_demo.sqlite3`,
con un año escolar completo: ~240 alumnos, pagos y morosos, asistencia, horarios sin cruces, notas
y libretas. **Tu base real (`db.sqlite3`) no se toca.**

Usuarios (clave `demo1234`): `admin` (administrador principal: módulos del sistema), `director`, `tesoreria`, `lmedina` (tutora de primaria), `lrios` (docente de secundaria).
Para regenerar los datos: `demo.bat nuevo`.
