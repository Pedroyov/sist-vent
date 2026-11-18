# Demo gratis en internet (Render)

Con esto tendrás **una demo por cada tipo de negocio**, cada una con su dirección para mandar por WhatsApp a tus clientes. Es gratis y no pide tarjeta.

| Negocio | Servicio en Render | Dirección (aprox.) |
|---|---|---|
| Restaurante / pollería | `sistema-ventas-demo` | `https://sistema-ventas-demo.onrender.com` |
| Bodega / tienda | `sistema-ventas-tienda` | `https://sistema-ventas-tienda.onrender.com` |
| Ropa y calzado | `sistema-ventas-ropa` | `https://sistema-ventas-ropa.onrender.com` |
| Librería | `sistema-ventas-libreria` | `https://sistema-ventas-libreria.onrender.com` |
| Peluquería / spa | `sistema-ventas-peluqueria` | `https://sistema-ventas-peluqueria.onrender.com` |
| Academia / gimnasio | `sistema-ventas-academia` | `https://sistema-ventas-academia.onrender.com` |

Si un nombre ya está ocupado, Render le agrega unas letras al final: la dirección real aparece arriba en cada servicio.

Así funcionan las demos:

- Cada una viene con los datos de ejemplo de su negocio (productos, ventas de la semana, caja, clientes y lo propio del rubro: mesas y cocina, citas o mensualidades). En la pantalla de ingreso aparecen solo los usuarios de prueba que sirven en ese negocio (clave `demo1234`).
- Cualquiera puede probar todo, pero no puede cambiar contraseñas, usuarios ni módulos.
- Si nadie la usa por 15 minutos, se "duerme". La siguiente visita tarda alrededor de **1 minuto** en cargar; después va normal. Ábrela tú un rato antes de mostrarla.
- Cada vez que se reinicia, vuelve a los datos de ejemplo, así que lo que alguien cambie no queda.
- **No es para negocios reales.** Para un cliente se usa un servidor pagado con PostgreSQL (configuración aparte, pendiente).

## 1. Subir el código a GitHub (una sola vez)

Si ya subes el sistema a GitHub con `git push`, sáltate este paso: Render usa ese mismo repositorio.

1. Crea una cuenta gratis en https://github.com.
2. Instala **GitHub Desktop**: https://desktop.github.com e inicia sesión con tu cuenta.
3. En GitHub Desktop: **File → Add local repository** y elige `C:\proyectos\sist-vent`.
   - Si dice que no es un repositorio, pulsa **create a repository** ahí mismo.
4. Pulsa **Publish repository** y deja marcada la opción **Keep this code private**, para que nadie más vea tu código.

El archivo `.gitignore` ya evita que se suban tu `.env`, tu base de datos real y las fotos.

## 2. Crear las demos en Render

1. Crea una cuenta gratis en https://render.com con la opción **GitHub** (así ya quedan conectados).
2. Pulsa **New → Blueprint**.
3. Elige tu repositorio `sist-vent` y pulsa **Connect**. Si no aparece, pulsa **Configure GitHub** y dale acceso a ese repositorio.
4. Render lee el archivo `render.yaml` y muestra los 6 servicios en plan **Free**. Pulsa **Apply** (o **Deploy Blueprint**).
5. Espera de 5 a 10 minutos. Cuando cada uno diga **Live**, arriba aparece su dirección `https://….onrender.com`. Esa es la que envías.

**Si ya tenías la demo del restaurante** creada con este paso: al subir el `render.yaml` nuevo (paso 3), Render agrega solo las 5 demos que faltan y deja la del restaurante como está. Si no aparecen, entra a **Blueprints**, elige el tuyo y pulsa **Manual Sync**.

## 3. Actualizar las demos cuando cambie el sistema

1. En GitHub Desktop: escribe un resumen abajo a la izquierda, pulsa **Commit to main** y luego **Push origin**.
2. Las demos **no se actualizan solas**: así no se gastan los 500 minutos de construcción gratis que Render da al mes (cada demo tarda unos 3 a 4 minutos en construirse). Actualiza solo la que vas a mostrar: en Render, entra al servicio → **Manual Deploy → Deploy latest commit**.

## Las fechas de la demo

Los datos de ejemplo se crean al instalar la demo, con las fechas de ese día (ventas de la semana, mesas abiertas, citas, cuotas por vencer). Si pasan varios días, "hoy" se ve vacío. Antes de mostrarla a un cliente: en Render, entra al servicio → **Manual Deploy → Deploy latest commit**. En unos minutos vuelve con las fechas del día (y con lo último del sistema).

## Límites del plan gratis

- **750 horas al mes para toda la cuenta**, compartidas entre todos tus servicios gratis (las 6 demos y también el del otro sistema). Solo cuentan mientras una demo está despierta; como se duermen a los 15 minutos sin uso, alcanza. No uses programas que las mantengan despiertas todo el tiempo: si se acaban las horas, todas se apagan hasta el mes siguiente.
- **500 minutos de construcción al mes.** Por eso las demos se actualizan a mano (paso 3) y no con cada push.
- **5 GB de transferencia al mes** y hasta 25 servicios en la cuenta.
- Las demos usan SQLite y vuelven a sus datos de ejemplo en cada despliegue. No uses la base PostgreSQL gratis de Render para las demos: vence a los 30 días y solo se permite una por cuenta.

Cada demo tiene fijo su negocio en la variable `DEMO_RUBRO` de `render.yaml` (`RES` restaurante, `TIE` tienda, `ROP` ropa, `LIB` librería, `PEL` peluquería, `ACA` academia o gimnasio con cobranzas). Si alguna no la necesitas, en Render entra al servicio → **Settings → Suspend** para que no gaste horas.

## Cambiar el nombre del negocio de la demo

Cada rubro de ejemplo trae su propio nombre (por ejemplo "Pollería El Buen Sabor" en restaurante). Para cambiarlo, entra a la demo como gerente → Configuración → Datos del negocio (se pierde al reiniciarse), o cámbialo en `productos/demo.py` y sube el cambio.
