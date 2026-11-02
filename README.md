# Demo Metraes · restaurante con varios locales

Perú Sistemas Pro E.I.R.L. — demo de flujo en tiempo real para restaurantes (Local A, B y C).

## Roles
| Ruta | Rol | Qué hace |
|---|---|---|
| `/duenos` | Dueños | Local A · B · C: caja, platos más vendidos, insumos consumidos y por agotarse, asistencia y lo que se le debe al personal. Hojas: Lista de compras, Personal (adelantos y pagos), Insumos |
| `/mozo?l=1` | Mozo | Toma pedidos (mesa, delivery, para llevar). Platos sin insumos aparecen agotados |
| `/cocina?l=1` | Cocina | Comandas en vivo con tiempo de espera; marca "Listo" |
| `/caja?l=1` | Caja y delivery | Cobra (efectivo, Yape/Plin, tarjeta), envía delivery, emite boleta |
| `/personal?l=1` | Personal | Marca entrada y salida |
| `/contador` | Contador | Comprobantes (aceptados, rechazados, en envío), SIRE, buzón SUNAT y SUNAFIL (vista de ejemplo) |
| `/panel` | Presentación | Mozo, cocina, caja y dueños en una pantalla |

`l=1`, `l=2`, `l=3` = Local A, B, C.

Reglas: al enviar un pedido se descuentan los insumos de cada receta; los insumos bajo el mínimo arman la lista de compras;
"se le debe" = días trabajados desde el último pago × jornal − adelantos.

## Personalizar
Variables opcionales en Railway: `DEMO_NEGOCIO` (nombre del restaurante) y `DEMO_DUENOS` (saludo del panel).

## Desplegar en Railway
1. Repo en GitHub con estos archivos en la raíz (`Procfile`, `requirements.txt`, `.python-version`).
2. Railway → New Project → Deploy from GitHub. Sin base de datos.
3. Custom Domain (por ejemplo `metraes.perusistemas.pro`) y CNAME en Cloudflare en modo DNS only.
4. Mantén 1 réplica. Para dejarla limpia: Panel de dueños → hoja Insumos → "Reiniciar demo" (toca dos veces).
