# Demo gratis en internet (Render)

Con esto tendrás una dirección como `https://sistema-ventas-demo.onrender.com` para mandar por WhatsApp a tus clientes. Es gratis y no pide tarjeta.

Así funciona la demo:

- Viene con los datos de ejemplo del **restaurante** (mesas, cocina, delivery, combos). En la pantalla de ingreso aparecen los usuarios de prueba (clave `demo1234`).
- Cualquiera puede probar todo, pero no puede cambiar contraseñas, usuarios ni módulos.
- Si nadie la usa por 15 minutos, se "duerme". La siguiente visita tarda alrededor de **1 minuto** en cargar; después va normal. Ábrela tú un rato antes de mostrarla.
- Cada vez que se reinicia, vuelve a los datos de ejemplo, así que lo que alguien cambie no queda.
- **No es para negocios reales.** Para un cliente se usa un servidor pagado (paso 7).

## 1. Subir el código a GitHub (una sola vez)

Si ya subes el sistema a GitHub con `git push`, sáltate este paso: Render usa ese mismo repositorio.

1. Crea una cuenta gratis en https://github.com.
2. Instala **GitHub Desktop**: https://desktop.github.com e inicia sesión con tu cuenta.
3. En GitHub Desktop: **File → Add local repository** y elige `C:\proyectos\sist-vent`.
   - Si dice que no es un repositorio, pulsa **create a repository** ahí mismo.
4. Pulsa **Publish repository** y deja marcada la opción **Keep this code private**, para que nadie más vea tu código.

El archivo `.gitignore` ya evita que se suban tu `.env`, tu base de datos real y las fotos.

## 2. Crear la demo en Render

1. Crea una cuenta gratis en https://render.com con la opción **GitHub** (así ya quedan conectados).
2. Pulsa **New → Blueprint**.
3. Elige tu repositorio `sist-vent` y pulsa **Connect**. Si no aparece, pulsa **Configure GitHub** y dale acceso a ese repositorio.
4. Render lee el archivo `render.yaml` y muestra el servicio `sistema-ventas-demo` en plan **Free**. Pulsa **Apply** (o **Deploy Blueprint**).
5. Espera de 5 a 10 minutos. Cuando diga **Live**, arriba aparece la dirección `https://….onrender.com`. Esa es la que envías.

## 3. Actualizar la demo cuando cambie el sistema

En GitHub Desktop: escribe un resumen abajo a la izquierda, pulsa **Commit to main** y luego **Push origin**. Render actualiza la demo solo, en unos minutos.

## Las fechas de la demo

Los datos de ejemplo se crean al instalar la demo, con las fechas de ese día (ventas de la semana, mesas abiertas, cuotas por vencer). Si pasan varios días, "hoy" se ve vacío. Antes de mostrarla a un cliente: en Render, entra al servicio → **Manual Deploy → Deploy latest commit**. En unos minutos vuelve con las fechas del día.

## Otro rubro (tienda, academia…)

En Render, entra al servicio → **Environment** → cambia `DEMO_RUBRO` (`RES` restaurante, `TIE` tienda, `ROP` ropa, `LIB` librería, `PEL` peluquería, `ACA` academia o gimnasio con cobranzas) → **Save, rebuild, and deploy**.

Si quieres dos demos a la vez (por ejemplo restaurante y academia), crea un segundo servicio con **New → Web Service**, el mismo repositorio y los mismos comandos de `render.yaml`, cambiando `DEMO_RUBRO`. Ojo: Render da **750 horas gratis al mes para toda la cuenta**, compartidas entre todos tus servicios gratis (también el del otro sistema). Como se duermen cuando nadie los usa, alcanza; solo no uses programas que los mantengan despiertos todo el tiempo.

## Cambiar el nombre del negocio de la demo

Cada rubro de ejemplo trae su propio nombre (por ejemplo "Pollería El Buen Sabor" en restaurante). Para cambiarlo, entra a la demo como gerente → Configuración → Datos del negocio (se pierde al reiniciarse), o cámbialo en `productos/demo.py` y sube el cambio.
