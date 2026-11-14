# Demo gratis en internet (Render)

Con esto tendrás una dirección como `https://sistema-ventas-demo.onrender.com` para mandar por WhatsApp a tus clientes. Es gratis y no pide tarjeta.

Así funciona la demo:

- Usa los datos de ejemplo. En la pantalla de ingreso aparecen los usuarios de prueba (clave `demo1234`).
- Cualquiera puede probar todo, pero no puede cambiar contraseñas, usuarios ni módulos.
- Si nadie la usa por 15 minutos, se "duerme". La siguiente visita tarda alrededor de **1 minuto** en cargar; después va normal. Ábrela tú un rato antes de mostrarla.
- Cada vez que se reinicia, vuelve a los datos de ejemplo, así que lo que alguien cambie no queda.
- **No es para negocios reales.** Para un cliente se usa un servidor pagado (paso 7).

## 1. Subir el código a GitHub (una sola vez)

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

## Cambiar el nombre del negocio de la demo

En Render, entra al servicio → **Environment** → cambia `NEGOCIO_NOMBRE` y `NEGOCIO_NOMBRE_CORTO` → **Save changes**.
