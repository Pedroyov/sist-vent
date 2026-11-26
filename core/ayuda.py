"""Ayuda de cada pantalla: el botón «?» junto al título abre para qué sirve y lo más usado.

Una entrada por pantalla, por su nombre de ruta («app:nombre»): (título, para qué sirve, [lo más usado], sección del manual).
Al crear una pantalla nueva, agrega aquí su ayuda (corta: 2 a 4 puntos) y, si en ella se hace un trabajo, su GUIA. Las pantallas sin entrada no muestran el botón.
"""
AYUDA = {
    # --- Inicio y cuenta ---
    "core:inicio": ("Inicio", "Tu resumen del día: lo pendiente, los números de hoy y accesos directos según tu trabajo.", [
        "Los avisos de arriba (en amarillo o rojo) son cosas por hacer: tócalos para ir directo.",
        "Las tarjetas muestran las ventas de hoy, la caja y lo que debes revisar.",
        "Cada persona ve solo lo que su rol le permite."], "2.3"),
    "seguridad": ("Código del celular", "Agrega un segundo paso al entrar: además de la clave, un código de 6 dígitos de una app del celular.", [
        "Escanea el código QR con Google Authenticator (o similar) y escribe el código que aparece.",
        "Guarda los códigos de respaldo: sirven si pierdes el celular.",
        "Para Administración es obligatorio en el sistema en la nube."], "2.4"),
    "password_change": ("Cambiar contraseña", "Cambia tu clave de ingreso.", [
        "Usa al menos 8 caracteres, mezclando letras y números.",
        "No uses la misma clave de tu correo o tu banco."], "19.2"),
    # --- Configuración ---
    "core:datos_negocio": ("Datos del negocio", "Lo que sale en tickets y boletas, cómo se cobra y qué funciones usa el negocio.", [
        "Nombre, RUC, dirección, logo y nota al pie del ticket.",
        "Métodos de pago que aceptas, descuentos, propina, días para devolver y para pagar el fiado.",
        "Papel de la ticketera (80, 76, 58 mm u hoja A4) y Funciones (variantes, combos, promociones…).",
        "Cambiar el tipo de negocio no enciende módulos: eso lo hace el administrador principal."], "3.1"),
    "core:modulos": ("Módulos", "Enciende o apaga partes enteras del sistema (mesas, caja, clientes, facturación…). Solo el administrador principal.", [
        "«Usar lo recomendado» deja los módulos típicos de tu tipo de negocio.",
        "Un módulo con datos no se apaga solo: así no se pierde nada."], "3.4"),
    "core:usuario_lista": ("Usuarios", "Quién entra al sistema y con qué rol.", [
        "Cada persona con su propio usuario: nunca compartas uno.",
        "Desactiva al que se va (no se borra: su historial queda).",
        "«Quitar código» si alguien perdió el celular del código de ingreso."], "3.6"),
    "core:usuario_nuevo": ("Nuevo usuario", "Crea el ingreso de una persona y elige su rol.", [
        "El rol decide qué ve y qué puede hacer (Cajero, Vendedor, Mozo, Cocina…).",
        "Si atiende citas o cobra comisión, enlázalo con su ficha de Personal."], "3.6"),
    "core:usuario_editar": ("Editar usuario", "Cambia el rol, la clave o desactiva a un usuario.", [
        "Desactivar no borra nada: sus ventas y movimientos quedan con su nombre."], "3.6"),
    "core:roles": ("Roles y permisos", "Qué puede hacer cada rol (Cajero, Vendedor, Mozo…).", [
        "Marca o desmarca permisos; afecta a todos los usuarios de ese rol.",
        "Puedes crear un rol nuevo copiando uno parecido."], "3.7"),
    "core:bitacora": ("Bitácora", "Registro de lo delicado: cambios de precio, anulaciones, permisos, cajas corregidas… No se puede borrar ni cambiar.", [
        "Filtra por fecha, tipo o usuario; baja todo en Excel.",
        "«Verificar» comprueba que nadie haya tocado los registros."], "19.3"),
    # --- Productos ---
    "productos:lista": ("Catálogo", "Todos tus productos y servicios, con precio y stock.", [
        "Busca, filtra por categoría o por «Por reponer».",
        "«Exportar» baja el catálogo en Excel; «Importar» carga muchos a la vez.",
        "Toca un producto para ver su ficha, stock y movimientos."], "4.2"),
    "productos:nuevo": ("Nuevo producto", "Crea un producto, servicio o combo.", [
        "Precio de venta y costo (para saber la ganancia).",
        "«Controlar stock» si quieres llevar la cuenta de unidades.",
        "Las tallas o tamaños se agregan después, en su ficha (Variantes)."], "4.2"),
    "productos:editar": ("Editar producto", "Cambia datos, precio, costo o foto.", [
        "Los cambios de precio y costo quedan en la bitácora."], "4.2"),
    "productos:detalle": ("Ficha del producto", "Todo de un producto: precio, stock, variantes y últimos movimientos.", [
        "«Stock» registra ingresos, salidas (merma) y conteos.",
        "Variantes: tallas, colores o tamaños con su propio precio y stock.",
        "Si usas Listas de precios, aquí se ponen los precios por cantidad o por tipo de cliente."], "4.4"),
    "productos:movimiento": ("Movimiento de stock", "Registra un ingreso, una salida (merma, uso interno) o un conteo.", [
        "Con «Conteo» pones lo que hay de verdad y el sistema ajusta la diferencia.",
        "Las compras a proveedores se registran mejor en Compras (también actualizan el costo)."], "4.4"),
    "productos:kardex": ("Movimientos de stock", "El kardex: cada entrada y salida de mercadería, con quién y cuándo.", [
        "Filtra por producto, tipo o fechas; baja en Excel."], "4.4"),
    "productos:categorias": ("Categorías", "Agrupa los productos (Bebidas, Platos, Útiles…) para encontrarlos rápido al vender.", [
        "El orden decide cómo salen en Vender.",
        "En restaurantes, cada categoría dice dónde se prepara (cocina, barra o mozo)."], "4.1"),
    "productos:importar": ("Importar desde Excel", "Carga o actualiza muchos productos a la vez con la plantilla.", [
        "Baja la plantilla, llénala y súbela: antes de guardar te muestra qué va a cambiar."], "4.7"),
    "productos:opciones": ("Opciones al pedir", "Lo que se elige al pedir: término de la carne, acompañamiento, adicionales con precio.", [
        "Un grupo (por ejemplo «Término») con sus opciones; luego se asigna a los platos.",
        "Puede ser obligatorio, de una o de varias opciones."], "4.5"),
    "productos:agotados": ("Agotados y porciones de hoy", "Lo que se acabó hoy y cuántas porciones quedan de cada plato.", [
        "Toca un plato para marcarlo agotado; mañana vuelve solo.",
        "Porciones de hoy: pon cuántas hay; avisa en amarillo (5) y rojo (2); con 0 queda agotado."], "5.2"),
    "productos:menu": ("Menú del día", "Arma lo que hay hoy en cada tipo de menú (económico, ejecutivo…): entradas, segundos, bebida y postre.", [
        "Toca los platos de hoy; los de otros días quedan guardados.",
        "«+ Tipo de menú» para otro precio con sus propios platos (o los mismos de otro tipo).",
        "«Copiar para WhatsApp» copia el menú de todos los tipos, con sus precios."], "5.1"),
    "productos:listas_precios": ("Listas de precios", "Tipos de cliente con sus precios (Mayorista, Revendedor).", [
        "Cada lista con un % menos sobre el precio normal.",
        "Se asigna al cliente en su ficha; al elegirlo en el cobro, la venta se recalcula."], "4.11"),
    "productos:promociones": ("Promociones", "2×1, 3×2, % de descuento o precio especial, con fechas y horario.", [
        "Se aplican solas al vender; gana la que más rebaja.",
        "Aquí ves cuál vale ahora y cuánto se vendió y rebajó este mes."], "4.12"),
    "productos:promocion_nueva": ("Nueva promoción", "Crea una promoción.", [
        "Elige el tipo, en qué productos o categorías y cuándo vale (fechas, días, horario)."], "4.12"),
    "productos:promocion_editar": ("Editar promoción", "Cambia o desactiva una promoción (no se borra).", [], "4.12"),
    # --- Vender ---
    "ventas:pos": ("Vender", "El punto de venta: arma la venta y cóbrala.", [
        "Busca por nombre o lee el código de barras; toca para agregar.",
        "Cobrar (o F9): elige cómo paga, el comprobante y, si hace falta, el cliente.",
        "Con listas de precios o promociones, el precio de cada línea cambia solo."], "7.1"),
    "ventas:lista": ("Ventas", "Todas las ventas, con filtros y totales.", [
        "Filtra por fechas, método, vendedor o cliente; baja en Excel.",
        "Abre una venta para imprimir, devolver productos o anular."], "7.5"),
    "ventas:ticket": ("Venta", "El detalle de una venta: ticket, pagos y comprobante.", [
        "Imprimir, enviar por WhatsApp, devolver productos o anular (con motivo).",
        "Si tiene boleta o factura, aquí está su estado en SUNAT y el PDF."], "7.3"),
    "ventas:devolver": ("Devolver productos", "Devuelve una parte de la venta (cambio de talla, producto fallado).", [
        "Marca cuántos de cada producto; si llegó dañado, sale como merma.",
        "Elige cómo se devuelve el dinero: caja, Yape, saldo a favor o descuento de su deuda."], "7.5"),
    "ventas:por_hacer": ("Boletas y facturas por hacer", "Ventas cobradas como nota de venta en las que el cliente pidió boleta o factura.", [
        "Hazla en tu sistema de siempre y escribe aquí su número («Ya la hice»).",
        "Luego «Enviar» abre el WhatsApp del cliente: adjunta el PDF.",
        "Solo aparece si no usas la facturación electrónica del sistema."], "13.9"),
    "impresion:cola": ("Cola de impresión", "Lo que se mandó a la ticketera de caja: lo que espera, lo que salió y lo que falló.", [
        "Reimprimir saca otra vez cualquier ticket o comanda (sale marcado como copia).",
        "Si dice «La estación no responde», prende la PC de caja y abre la Estación de impresión: lo pendiente sale solo."], "3.3"),
    "impresion:estacion": ("Estación de impresión", "Esta PC imprime sola los tickets, comandas, precuentas y cierres de todos los equipos.", [
        "Déjala abierta todo el turno; Chrome tiene que abrirse con --kiosk-printing.",
        "La ticketera tiene que ser la impresora predeterminada de Windows."], "3.3"),
    "ventas:conciliar": ("Conciliar Yape y bancos", "Compara lo cobrado con Yape, Plin, tarjeta y transferencia con lo que llegó al banco.", [
        "Cada día y método: escribe lo que dice el banco; el sistema calcula la diferencia.",
        "Si algo no llegó, márcalo: queda como faltante de quien cobró.",
        "Baja el resumen en Excel o imprímelo."], "6.9"),
    # --- Caja ---
    "caja:mi_caja": ("Mi caja", "Tu turno de caja: abrir, ver cómo va y cerrar.", [
        "Abre con el sencillo que hay en el cajón.",
        "Registra ingresos o salidas (por ejemplo, movilidad) durante el turno.",
        "Al cerrar cuenta el efectivo: el sistema dice si cuadra."], "6.1"),
    "caja:sesion": ("Caja", "El detalle de un turno de caja: ventas, cobros, salidas y cierre.", [
        "Imprime el cierre.",
        "Si algo no está bien en una caja cerrada, Administración la corrige abajo (sin reabrirla)."], "6.6"),
    "caja:cerrar": ("Cerrar caja", "Cuenta el efectivo del cajón y cierra el turno.", [
        "Cuenta billete por billete; si no cuadra por más de S/ 1, te pide contar otra vez.",
        "Indica cuánto dejas en el cajón para el siguiente turno."], "6.3"),
    "caja:historial": ("Historial de cajas", "Todos los turnos de caja, abiertos y cerrados, con sus diferencias.", [
        "Filtra por cajero o estado; baja en Excel."], "6.4"),
    "caja:gastos": ("Gastos", "Todo lo que salió: de las cajas y fuera de caja (alquiler, sueldos, transferencias).", [
        "Por motivo y en detalle, del periodo que elijas.",
        "«Gasto fuera de caja» para lo que no salió del cajón.",
        "Baja en Excel o imprime."], "6.7"),
    "caja:puntos": ("Cajas y series", "Cada caja física (Caja 1, Barra) con sus propias series de boletas y facturas.", [
        "Útil si cobras en más de un lugar o tienes otro local con su serie."], "6.5"),
    # --- Mesas, cocina y delivery ---
    "mesas:mapa": ("Mesas", "El mapa del local: qué mesas están libres, ocupadas o por cobrar.", [
        "Toca una mesa libre para abrirla; una ocupada para ver su cuenta.",
        "Los colores dicen en qué está cada mesa (ver el manual)."], "8.1"),
    "mesas:cuenta": ("Cuenta de la mesa", "Lo pedido en la mesa: por enviar, en cocina y por cobrar.", [
        "Agregar pide platos; «Enviar» los manda a preparar.",
        "Cada plato dice quién lo pidió si no fue el mozo de la mesa; toca el nombre del mozo (⇆) para pasar la mesa.",
        "Cobrar (cajero): todo junto, por platos o dividido entre personas.",
        "Al dividir, de 4 gaseosas eliges cuántas paga cada uno."], "9.1"),
    "mesas:agregar": ("Tomar pedido", "Elige los platos y bebidas de la mesa.", [
        "Toca para agregar; las opciones (término, acompañamiento) se eligen al tocar.",
        "«Quedan 3» en amarillo o rojo: se están acabando las porciones de hoy.",
        "«Llevar» en un plato: cocina lo empaca para llevar y se cobra en la misma mesa."], "8.2"),
    "mesas:configurar": ("Zonas y mesas", "Arma el mapa del local: zonas (Salón, Terraza) y sus mesas.", [
        "Cambia nombres y personas de varias mesas y guarda una vez."], "3.8"),
    "mesas:cocina": ("Pantalla de cocina", "Los pedidos por preparar, en orden de llegada.", [
        "Toca un plato (o la comanda entera) cuando esté listo: el mozo recibe el aviso.",
        "Arriba: los platos con pocas porciones hoy."], "10"),
    "mesas:pedidos": ("Delivery", "Los pedidos para enviar: por despachar, en camino y por cobrar.", [
        "Nuevo pedido con el celular del cliente (recuerda su dirección).",
        "«Salió» con el repartidor imprime su hoja; al volver, cobra y marca entregado."], "11"),
    # --- Clientes ---
    "clientes:lista": ("Clientes", "Tus clientes, lo que deben y con qué lista de precios compran.", [
        "Filtra los que deben o tienen fiado vencido; baja en Excel.",
        "Toca uno para ver su ficha y registrar pagos."], "12.1"),
    "clientes:nuevo": ("Nuevo cliente", "Registra un cliente (para fiar, facturar o recordarlo).", [
        "Con RUC, el sistema valida el número.",
        "Límite y días para pagar si se le fía."], "12.1"),
    "clientes:editar": ("Editar cliente", "Datos, límite de fiado, plazo y lista de precios del cliente.", [
        "Límite, plazo y lista solo los cambia quien tiene permiso; queda en la bitácora."], "12.1"),
    "clientes:detalle": ("Ficha del cliente", "Lo que debe, qué venció, su saldo a favor y sus compras.", [
        "Registrar pago, recordar la deuda por WhatsApp o imprimir el estado de cuenta.",
        "Saldo a favor: de devoluciones y del monedero; se usa al cobrar."], "12.3"),
    # --- Reportes ---
    "reportes:inicio": ("Reportes", "Cómo va el negocio en el periodo: ventas, ganancia, productos, gastos, caja y control.", [
        "Elige el periodo arriba; el índice salta a cada parte.",
        "Excel trae todo en hojas; el botón de impresora lo imprime o guarda como PDF."], "14"),
    "reportes:dinero": ("Dinero del día", "Día por día: lo que entró, lo que salió y dónde quedó el dinero.", [
        "Efectivo y cada medio electrónico, gastos y retiros.",
        "Baja en Excel o imprime."], "14.2"),
    # --- Facturación ---
    "facturacion:lista": ("Comprobantes", "Boletas, facturas y notas de crédito emitidas, con su estado en SUNAT.", [
        "Reenvía lo que no llegó (hay 3 días de plazo).",
        "«Excel para el contador» baja el registro de ventas del mes."], "13.3"),
    "facturacion:configurar": ("Facturación electrónica", "Conexión con Nubefact, series y opciones de boletas y facturas.", [
        "Empieza en modo prueba; cuando todo cuadre, pasa a SUNAT real.",
        "El token se guarda cifrado."], "13.7"),
    # --- Cobranzas ---
    "cobranzas:inicio": ("Cobranzas", "Mensualidades y cuotas: quién paga hoy, quién está atrasado.", [
        "Busca a la persona para cobrar o ver su cuenta.",
        "Inscribe a alguien nuevo en un plan."], "15.1"),
    "cobranzas:inscritos": ("Inscritos", "Todas las personas inscritas y su situación; se baja en Excel.", [], "15.6"),
    "cobranzas:morosos": ("Morosos", "Quién debe cuotas vencidas, con recordatorio por WhatsApp.", [], "15.7"),
    "cobranzas:planes": ("Planes", "Los planes (mensualidad, curso, membresía) con su precio y cuotas.", [], "15.2"),
    "cobranzas:reporte": ("Reporte de cobranzas", "Lo cobrado y lo pendiente del periodo; se imprime o baja en Excel.", [], "15.9"),
    "cobranzas:cuenta": ("Cuenta de la persona", "Sus cuotas, pagos y lo que debe.", [
        "Cobrar una o varias cuotas; imprimir recibo."], "15.5"),
    # --- Reservas y citas ---
    "reservas:agenda": ("Reservas", "Las reservas del día y de los próximos días.", [
        "Nueva reserva con el celular del cliente; confírmala por WhatsApp.",
        "Cuando llegan, «Llegó» abre su mesa. Baja el día en Excel o imprímelo."], "16.1"),
    "reservas:nueva": ("Nueva reserva", "Toma una reserva: día, hora, personas y mesa.", [], "16.2"),
    "citas:agenda": ("Agenda de citas", "Las citas del día por persona que atiende.", [
        "Toca un espacio libre para agendar; toca una cita para confirmarla, atenderla o cobrarla.",
        "Baja el día en Excel."], "17.2"),
    "citas:mi_agenda": ("Mi agenda", "Tus citas del día y tus números del mes (para quien atiende).", [
        "«Registrar servicio» para un cliente que llegó sin cita: avisa a caja para cobrar."], "17.7"),
    "citas:nueva": ("Nueva cita", "Agenda una cita: servicio, quién atiende, día y hora.", [], "17.3"),
    "citas:horarios": ("Horarios", "Los días y horas en que atiende cada persona, y sus ausencias.", [], "17.1"),
    "citas:por_cobrar": ("Servicios por cobrar", "Lo que ya se atendió y falta cobrar en caja.", [
        "«Cobrar» lleva los servicios a Vender; «Ya cobrado» si se cobró aparte."], "17.5"),
    # --- Compras ---
    "compras:lista": ("Compras", "Las compras a proveedores del periodo, con lo pagado y lo que falta.", [
        "Nueva compra suma el stock y actualiza el costo promedio.",
        "Baja en Excel o imprime."], "18.2"),
    "compras:nueva": ("Nueva compra", "Lo que compras para vender o preparar: mercadería, insumos, verduras, bebidas.", [
        "Agrega los productos con cantidad y costo; al guardar suben al stock. Fletes o insumos sin producto: línea libre.",
        "¿Mercado o ambulante? Deja el proveedor vacío: queda en «Proveedor varios».",
        "Al crédito sí elige el proveedor y pon cuándo vence.",
        "Luz, alquiler, movilidad o limpieza no son compras: van en Gastos."], "18.2"),
    "compras:por_pagar": ("Por pagar", "Lo que se debe a cada proveedor, lo vencido primero.", [
        "Paga una compra o al proveedor de una vez (va a lo más antiguo).",
        "Baja en Excel o imprime."], "18.3"),
    "compras:reponer": ("Reponer", "Lo que llegó a su stock mínimo, agrupado por proveedor, para hacer el pedido.", [
        "Envía el pedido por WhatsApp al proveedor; baja la lista en Excel o imprímela."], "18.4"),
    "compras:proveedores": ("Proveedores", "Tus proveedores y cuánto se le debe a cada uno; se baja en Excel.", [], "18.1"),
    # --- Personal ---
    "personal:lista": ("Personal", "Las personas que trabajan en el negocio (atiendan citas, cobren comisión o sueldo).", [
        "No es lo mismo que Usuarios: aquí también va quien no entra al sistema."], "3.9"),
    "personal:pagos": ("Pagos al personal", "Cuánto le toca a cada persona en el periodo, cuánto ya se le pagó y cuánto falta.", [
        "Paga desde aquí (de tu caja o fuera de caja).",
        "Baja en Excel o imprime."], "6.8"),
}


# Paso a paso y «Ojo» de las pantallas donde se hace un trabajo y es fácil equivocarse: {clave: ([pasos], [ojo])}.
# Las claves también deben estar en AYUDA. Pasos cortos (3 a 5); en «Ojo», el error más común y cómo evitarlo.
GUIA = {
    "productos:menu": ([
        "Cada mañana: «Empezar de cero» si el menú cambia todo.",
        "En cada tipo de menú, toca los platos de hoy o escribe uno nuevo (entrada, segundo, bebida, postre).",
        "Si algo se acaba, tócalo como agotado: en las mesas sale tachado.",
        "«Copiar para WhatsApp» y pégalo en tus estados o grupos."], [
        "Si un grupo dice «también Menú económico», lo que cambies ahí cambia en los dos menús.",
        "El nombre o el precio del menú se cambia con el lápiz (es un producto)."]),
    "impresion:estacion": ([
        "Instala la ticketera en Windows y déjala como impresora predeterminada.",
        "Abre Chrome con un acceso directo que tenga --kiosk-printing al final del «Destino».",
        "Entra con un usuario de caja y abre esta pantalla. Déjala abierta todo el turno."], [
        "Si aparece la ventana de impresión, Chrome no se abrió con --kiosk-printing: ciérralo del todo y ábrelo con el acceso directo.",
        "Si apagas esta PC, lo que se pida queda en cola y sale al volver a abrir esta pantalla."]),
    "ventas:pos": ([
        "Toca los productos o escanea su código (lector o el botón de la cámara).",
        "Corrige cantidades con − y + en el carrito.",
        "Pulsa Cobrar (o F9). Si pide boleta o factura, elígela arriba y escribe sus datos.",
        "Elige cómo paga; en efectivo escribe con cuánto paga y mira el vuelto.",
        "Confirmar. Imprime el ticket o envíalo por WhatsApp."], [
        "Boleta o factura se elige antes de Confirmar: después ya no se cambia desde aquí.",
        "Para fiar, primero elige el cliente (Cliente y nota) y luego el método Fiado.",
        "En Yape o Plin anota el N° de operación: sirve para conciliar con el banco."]),
    "caja:mi_caja": ([
        "Al empezar el turno: Abrir caja y escribe con cuánto sencillo empiezas.",
        "Si sale dinero del cajón (movilidad, pago a un proveedor), regístralo como salida con su motivo.",
        "Si entra dinero que no es venta (sencillo que trajeron), regístralo como ingreso.",
        "Al terminar: Cerrar caja."], [
        "Toda salida del cajón se anota en el momento: si no, al cerrar faltará dinero.",
        "Un retiro del dueño no es gasto: elige ese motivo para que no baje la ganancia."]),
    "caja:cerrar": ([
        "Separa solo el efectivo (Yape, tarjeta y fiado no se cuentan).",
        "Escribe cuántos billetes y monedas hay de cada uno; el sistema suma.",
        "Escribe cuánto dejas en el cajón para el siguiente turno.",
        "Pulsa Cerrar caja e imprime el cierre para entregarlo con el dinero."], [
        "No ves cuánto debería haber: cuenta con calma. Si no cuadra por más de S/ 1, te pide contar otra vez.",
        "Si después recuerdas una salida que no anotaste, avisa a Administración: la corrige sin reabrir la caja."]),
    "mesas:agregar": ([
        "Toca los platos; lo más vendido sale primero.",
        "Si el plato tiene opciones (término, acompañamiento), elígelas en la ventana que se abre.",
        "Escribe en la nota lo especial («sin cebolla»); «Llevar» si se lo llevan empacado.",
        "Al terminar, agrega y envía: va a cocina o barra (o solo «Agregar» para enviarlo después)."], [
        "Lo que no envías, cocina no lo ve: revisa que no quede nada en «Por enviar».",
        "«Quedan 3» en amarillo o rojo: avisa al cliente antes de que se acabe."]),
    "mesas:cuenta": ([
        "Tomar pedido para agregar; Enviar para mandar a cocina lo nuevo.",
        "Cuando suena la campana, lleva el plato y pulsa «Ya serví lo listo».",
        "Precuenta para que el cliente revise antes de pagar.",
        "Cobrar (cajero): todo junto, o ⋯ → Dividir cuenta para que cada uno pague lo suyo."], [
        "Al dividir, de 4 gaseosas elige cuántas paga esa persona: el resto queda en la cuenta.",
        "Quitar un plato ya enviado necesita permiso y un motivo (queda registrado).",
        "Si se van sin pagar todo, no liberes la mesa: queda lo pendiente."]),
    "mesas:cocina": ([
        "Los pedidos salen en orden de llegada; el tiempo arriba dice cuánto llevan esperando.",
        "Toca un plato cuando esté listo, o LISTO para toda la comanda.",
        "El mozo recibe el aviso en su celular."], [
        "Lo tachado en rojo lo quitaron después de pedirlo: no lo prepares.",
        "«PARA LLEVAR»: va empacado.",
        "Si se acaba un plato, avisa para marcarlo agotado o poner las porciones que quedan."]),
    "mesas:pedidos": ([
        "Nuevo pedido: escribe el celular; si ya pidió antes, su dirección sale sola.",
        "Agrega los productos y el costo de envío.",
        "«Salió» con el repartidor: imprime su hoja con dirección y vuelto.",
        "Al volver, cobra y queda como entregado."], [
        "Anota con cuánto paga el cliente: así el repartidor lleva el vuelto exacto."]),
    "productos:nuevo": ([
        "Escribe el nombre y elige la categoría.",
        "Pon el precio de venta y el costo (para saber cuánto ganas).",
        "Escanea el código de barras si tiene (lector o cámara).",
        "Si llevas la cuenta de unidades, activa «Controlar stock» y pon cuántas tienes.",
        "Guarda. Tallas, colores o tamaños se agregan después en su ficha."], [
        "Sin costo, los reportes no pueden calcular tu ganancia.",
        "Un código de barras no se puede repetir en dos productos."]),
    "compras:nueva": ([
        "Elige el proveedor (o déjalo vacío si es del mercado: «Proveedor varios»).",
        "Elige el documento (factura, boleta, sin documento) y su número.",
        "Agrega cada producto con cantidad y costo; fletes o insumos sin producto como línea libre.",
        "Indica cómo se paga: de tu caja, fuera de caja o al crédito.",
        "Guarda: el stock sube y el costo se actualiza solo."], [
        "Luz, alquiler, movilidad o limpieza no son compras: van en Gastos.",
        "Al crédito sí hay que elegir el proveedor: es a quien le debes.",
        "El costo es por unidad, no el total de la línea."]),
    "caja:gastos": ([
        "Elige el periodo (hoy, este mes…) para ver todo lo que salió.",
        "«Gasto fuera de caja» para lo pagado por transferencia, Yape o con dinero que no estaba en el cajón.",
        "Elige el motivo correcto y escribe el detalle («Luz de octubre»)."], [
        "Lo que sale del cajón durante el turno se registra en Caja, no aquí.",
        "Un gasto mal registrado se anula con motivo; no se borra."]),
    "clientes:detalle": ([
        "Arriba ves cuánto debe y qué está vencido (en rojo).",
        "Registrar pago: escribe cuánto paga y cómo; se aplica a lo más antiguo primero.",
        "Recordar deuda: abre WhatsApp con el mensaje listo y las fechas.",
        "Imprime el estado de cuenta si lo pide."], [
        "El saldo a favor se usa al cobrar con el método «Saldo a favor»; no se descuenta solo.",
        "Con algo vencido, el sistema no deja fiarle más (salvo a quien tiene permiso)."]),
    "ventas:ticket": ([
        "Imprimir o enviar por WhatsApp el ticket.",
        "Devolver productos si trae algo de vuelta (cambio, producto fallado).",
        "Anular solo si la venta entera estuvo mal (con motivo)."], [
        "Si ya tiene devoluciones, no se puede anular entera: devuelve lo que falta.",
        "Anular una venta con boleta o factura genera su nota de crédito."]),
    "ventas:devolver": ([
        "Marca cuántas unidades de cada producto devuelve.",
        "Si llegó dañado, márcalo como merma (no vuelve al stock).",
        "Elige cómo le devuelves el dinero: de la caja, fuera de caja, saldo a favor o descontando su deuda.",
        "Escribe el motivo y confirma."], [
        "Devolver de la caja necesita la caja abierta con efectivo suficiente.",
        "Con boleta o factura, el sistema hace la nota de crédito por lo devuelto."]),
    "ventas:por_hacer": ([
        "Haz la boleta o factura en tu sistema de siempre (SUNAT o tu facturador) con los datos que se ven.",
        "Escribe aquí su número (por ejemplo B001-123) y toca «Ya la hice».",
        "En «Ya hechas», toca Enviar: abre el WhatsApp del cliente.",
        "Adjunta el PDF en el chat y envía."], [
        "Hazlas el mismo día de la venta, con la misma fecha.",
        "Si anotaste mal el número, Deshacer la regresa a «por hacer»."]),
    "cobranzas:cuenta": ([
        "Marca las cuotas que paga (las vencidas primero).",
        "Elige cómo paga y confirma.",
        "Imprime o envía el recibo por WhatsApp."], [
        "Dar de baja deja de generar cuotas nuevas, pero lo vencido se sigue debiendo.",
        "Una beca o cortesía se exonera con motivo; no se cobra en S/ 0."]),
}


def de(request):
    """La ayuda de la pantalla actual (o None)."""
    m = getattr(request, "resolver_match", None)
    if not m or not m.url_name:
        return None
    clave = f"{m.namespace}:{m.url_name}" if m.namespace else m.url_name
    datos = AYUDA.get(clave)
    if not datos:
        return None
    titulo, para_que, puntos, seccion = datos
    pasos, ojo = GUIA.get(clave, ([], []))
    # ancla de la sección en el manual dentro del sistema (la misma que pone `manage.py generar_manual`)
    ancla = "s-" + str(seccion).strip(".").replace(".", "-")
    return {"titulo": titulo, "para_que": para_que, "puntos": puntos, "seccion": seccion, "pasos": pasos, "ojo": ojo, "ancla": ancla}
