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

## Copias de seguridad (importante)

Toda la información del negocio está en `db.sqlite3` y las fotos en `media/`. Si la PC se malogra o la roban, se pierde todo. Por eso:

- `respaldo.bat` (o `python manage.py respaldo`) crea un `.zip` con la base de datos y las fotos en la carpeta `respaldos/`, y deja los últimos 30.
- Para que sea **automático todos los días**: Programador de tareas de Windows → *Crear tarea básica* → *Diariamente* (por ejemplo a las 11 p. m.) → *Iniciar un programa* → elige `respaldo.bat`.
- Guarda los respaldos **fuera de la PC**: `respaldo.bat "C:\Users\TU_USUARIO\Google Drive\Respaldos"` (o OneDrive, o una USB).
- Para restaurar: cierra el sistema, descomprime el `.zip`, pon el `db.sqlite3` en la carpeta del proyecto y la carpeta `media/` junto a él.

## Estructura

Ver [ARQUITECTURA.md](ARQUITECTURA.md).

## Avance

- [x] **Base** – Login con bloqueo, usuarios, roles y permisos, módulos activables, datos del negocio (rubro, logo, RUC), PWA instalable
- [x] **Productos** – Productos y servicios, categorías, variantes (talla, color, tamaño), códigos de barras, stock con kardex, importar y exportar Excel
- [x] **Punto de venta** – Venta rápida con lectora de códigos, variantes, cobro en efectivo con vuelto, Yape, Plin, tarjeta o mixto, ticket 80 mm y WhatsApp, ventas del día por método, anulaciones
- [x] **Caja** – Turno por cajero, ingresos y egresos, cierre con conteo de billetes y diferencia, historial
- [x] **Mesas** – Mapa de mesas en vivo, pedidos desde el celular con notas, envío a cocina, precuenta, cambiar y juntar mesas, cobro total o dividido, para llevar, propina opcional, pantalla de cocina con sonido
- [x] **Opciones al pedir y agotados** – Término, acompañamiento, adicionales con precio y cremas al pedir; platos u opciones agotados por el día
- [x] **Impresión** – Ticket, precuenta, comanda y cierre de caja del tamaño del rollo (80 o 58 mm)
- [x] **Clientes y fiado** – Clientes con DNI/RUC validado, venta al fiado con límite, pagos de deudas que entran a la caja, estado de cuenta, recordatorio por WhatsApp
- [x] **Reportes** – Ventas comparadas con el periodo anterior, por día/hora/día de la semana, lo más y lo menos vendido, categorías, personal y mozos, mesas y platos quitados, inventario y mermas, deudores, diferencias de caja y anulaciones; Excel
- [ ] Despliegue con HTTPS

## Ver el sistema con datos de ejemplo

Doble clic en `demo.bat`. Crea una base aparte, `db_demo.sqlite3`, con un negocio de ejemplo (bodega). Para otro rubro: `python manage.py datos_demo --rubro ROP` (ROP ropa, RES restaurante, LIB librería, PEL peluquería) sobre una base vacía. **Tu base real (`db.sqlite3`) no se toca.**

Usuarios (clave `demo1234`): `admin` (administrador principal: módulos del sistema), `gerente` (Administración), `cajero`, `vendedor`.
Para regenerar los datos: `demo.bat nuevo`.
