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
- [x] **Pagar antes o al final** – Al cobrar se envía a cocina lo que faltaba; la mesa puede quedar "Pagada" mientras siguen comiendo o esperan su plato, se puede seguir pidiendo y se libera cuando se van
- [x] **Delivery** – Módulo propio con su entrada en el menú, para restaurantes y tiendas (no necesita Mesas); también se crea desde Vender con el carrito armado. Pedidos por teléfono o WhatsApp: el cliente se reconoce por su celular, costo de envío, "paga con" y vuelto, repartidor, estados (preparando, en camino, entregado), hoja para el repartidor y reporte por repartidor
- [x] **Nivel de detalle de los pedidos** – Simple, con opciones o detallado: cada negocio usa solo lo que necesita
- [x] **Qué lleva cada plato** – Lo que lleva (pollo, papas, ensalada): quitar algo («SIN ENSALADA» en la comanda) o cambiarlo (papas por arroz); las opciones que vienen incluidas ya aparecen elegidas
- [x] **Menú del día** – Entrada y segundo que cambian cada día, con los platos de otros días a un toque, segundos con precio extra, agotados y texto listo para WhatsApp
- [x] **Partes iguales** – Dividir la cuenta entre N personas; cada una paga con su método (Yape, tarjeta, efectivo con su vuelto)
- [x] **Cortesías y descuentos** – Platos de la casa (todo o parte) y descuento en soles o % al cobrar, siempre con motivo; si el usuario no tiene permiso, un supervisor autoriza con su usuario y clave; todo queda en Reportes → Control
- [x] **Facturación electrónica** – Boleta o factura al cobrar (o después desde la venta), IGV por línea, QR, reenvío si no hay internet, nota de crédito al anular; modo prueba y conector Nubefact
- [x] **Rol Mozo** – En restaurantes: toma pedidos y entrega la precuenta; el cobro se hace en caja
- [x] **Mesas juntas** – Una cuenta puede ocupar varias mesas pegadas (familias); se separan o se liberan juntas
- [x] **Cocina, barra o mozo** – Cada categoría o producto dice dónde se prepara: cocina, barra (pantalla y comanda propias) o lo lleva el mozo directo (gaseosas)
- [x] **Aviso al mozo** – Suena y vibra en el celular cuando algo está listo para llevar
- [x] **Combos** – Un producto que trae otros (fijos y partes a elegir) a un precio especial; descuenta el stock de cada uno
- [x] **Cajas y series** – Varios puntos de cobro (Caja 1, Barra); cada uno puede tener su serie de boletas y facturas
- [x] **Factura al crédito** – Apagada por defecto. Factura con forma de pago Crédito y cuotas; cuenta corriente por cliente con vencidos, bloqueo de fiado si debe algo vencido, deudas incobrables y Excel mensual para el contador
- [x] **Tipo de negocio** – Cada rubro recomienda sus módulos, trae visibles solo las funciones que usa (variantes, combos, servicios, agotados; se marcan en Datos del negocio) y adapta palabras del menú (Carta, Venta rápida, Mensualidades…). Cambiar de rubro nunca oculta lo que ya se usa
- [x] **Cobranzas (mensualidades)** – Para academias, gimnasios y talleres: planes (mensual, quincenal, semanal, por número de cuotas o pago único, con matrícula), inscripciones con alumno distinto al que paga y precio con descuento, cuotas que se generan solas, cobro en caja con recibo (todo o a cuenta), adelantar periodos, bajas, exoneraciones, mora opcional, morosos y por vencer con WhatsApp, reporte mensual y Excel. Funciona sin el punto de venta
- [x] **Personal** – Una sola lista de quienes trabajan (con o sin usuario) para todo el sistema: agenda de citas, repartidores, «quién atendió» en Vender. Reporte único de Personal que se adapta al negocio (cobró, atendió, propinas, servicios, ocupación, entregas) y comisiones opcionales
- [x] **Reservas** – Para restaurantes: agenda por día con personas, mesa opcional y nota; aviso si la mesa ya está reservada; confirmación y recordatorio por WhatsApp; una o varias mesas (grupos grandes, se juntan solas); la mesa se ve «Reservada» en el mapa y al llegar se abre la cuenta; atrasadas y «No vino»; historial por celular
- [x] **Citas y agenda** – Para peluquerías, spas y consultorios: personal con servicios, horario semanal, refrigerio, días libres y vacaciones; agenda del día por columnas; horarios libres según la duración del servicio; si su persona de confianza está ocupada, la próxima hora con ella o quién más atiende a esa hora; «suele atenderse con»; WhatsApp; atender y cobrar en Vender; cliente sin cita: el trabajador registra lo que hizo y caja lo cobra desde «Servicios por cobrar»; cada trabajador con su usuario ve su agenda y comparte sus horarios libres; sus servicios, ocupación y comisión salen en el reporte de Personal
- [x] **Reglas de cobro** – El negocio elige qué métodos de pago acepta y si usa propinas, descuentos y cortesías; cobro compacto para celular
- [ ] Despliegue con HTTPS

## Ver el sistema con datos de ejemplo

Doble clic en `demo.bat` (bodega) o, en una ventana de comandos, `demo.bat pel` (TIE tienda, RES restaurante, ROP ropa, LIB librería, PEL peluquería, ACA academia o gimnasio). Cada negocio tiene su propia base (`db_demo_pel.sqlite3`…), así que cambiar de negocio no borra las demás; `demo.bat pel nuevo` la vuelve a generar con las fechas de hoy. Funciona como las demos de Render (modo demo: la pantalla de ingreso muestra los usuarios de prueba). **Tu base real (`db.sqlite3`) no se toca.**

Usuarios (clave `demo1234`): `admin` (administrador principal: módulos del sistema), `gerente` (Administración), `cajero`, `vendedor`.
Para regenerar los datos de un negocio con las fechas de hoy: `demo.bat pel nuevo`.
