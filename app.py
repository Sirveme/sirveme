"""
Demo Metraes · restaurante con varios locales — Perú Sistemas Pro E.I.R.L.

Pedidos (mozo) -> Cocina -> Caja / Delivery, en tiempo real.
Cada plato vendido descuenta sus insumos (receta) y arma la lista de compras.
Asistencia y liquidación del personal: "cuánto se le debe" en cualquier momento.
Panel de dueños: Local A | Local B | Local C.

Starlette (base de FastAPI) + Jinja2 + Vanilla JS. Tiempo real con Server-Sent Events.
SQLite para la demo (se vuelve a sembrar al reiniciar). En producción: PostgreSQL.
"""
import asyncio
import json
import math
import os
import random
import sqlite3
import threading
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

BASE = Path(__file__).parent
DB_PATH = os.environ.get("DEMO_DB", str(BASE / "demo.db"))
NEGOCIO = os.environ.get("DEMO_NEGOCIO", "Chara Point")
DUENOS = os.environ.get("DEMO_DUENOS", "Gino y Rosa")
LIMA = timezone(timedelta(hours=-5))

templates = Jinja2Templates(directory=str(BASE / "templates"))
templates.env.globals.update(NEGOCIO=NEGOCIO, DUENOS=DUENOS)

_lock = threading.Lock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row

ESQUEMA = """
CREATE TABLE IF NOT EXISTS locales(id INTEGER PRIMARY KEY, letra TEXT, nombre TEXT, sub TEXT, serie TEXT, base INTEGER);
CREATE TABLE IF NOT EXISTS insumos(id INTEGER PRIMARY KEY, nombre TEXT, unidad TEXT, costo REAL);
CREATE TABLE IF NOT EXISTS stock(local_id INTEGER, insumo_id INTEGER, cant REAL, minimo REAL, objetivo REAL,
  PRIMARY KEY(local_id, insumo_id));
CREATE TABLE IF NOT EXISTS platos(id INTEGER PRIMARY KEY, nombre TEXT, cat TEXT, precio REAL, color TEXT);
CREATE TABLE IF NOT EXISTS receta(plato_id INTEGER, insumo_id INTEGER, cant REAL);
CREATE TABLE IF NOT EXISTS personal(id INTEGER PRIMARY KEY, local_id INTEGER, nombre TEXT, puesto TEXT,
  jornal REAL, desde TEXT, t_registro INTEGER);
CREATE TABLE IF NOT EXISTS asistencia(id INTEGER PRIMARY KEY, personal_id INTEGER, fecha TEXT, entrada TEXT, salida TEXT);
CREATE TABLE IF NOT EXISTS pagos(id INTEGER PRIMARY KEY, personal_id INTEGER, fecha TEXT, ts TEXT, monto REAL, tipo TEXT);
CREATE TABLE IF NOT EXISTS pedidos(id INTEGER PRIMARY KEY, local_id INTEGER, numero TEXT, tipo TEXT, mesa TEXT,
  cliente TEXT, direccion TEXT, mozo TEXT, estado TEXT, creado TEXT, listo TEXT, despachado TEXT, pagado TEXT,
  metodo TEXT, total REAL, comprobante TEXT, comp_estado TEXT, fecha TEXT);
CREATE TABLE IF NOT EXISTS items(pedido_id INTEGER, plato_id INTEGER, cant INTEGER, precio REAL);
CREATE TABLE IF NOT EXISTS mov_insumo(id INTEGER PRIMARY KEY, ts TEXT, fecha TEXT, local_id INTEGER, insumo_id INTEGER,
  cant REAL, tipo TEXT, ref TEXT);
"""

# ------------------------------------------------------------------ datos de ejemplo
LOCALES = [("A", "Local A", "Iquitos", "B001", 4810), ("B", "Local B", "Iquitos", "B002", 3266),
           ("C", "Local C", "Local nuevo", "B003", 211)]
ESCALA_LOCAL = {"A": 1.0, "B": 0.9, "C": 0.55}

# nombre, unidad, costo por unidad, mínimo, objetivo (para un local tipo A)
INSUMOS = [
    ("Pescado fresco", "kg", 22.0, 8, 25), ("Mariscos mixtos", "kg", 28.0, 4, 12), ("Paiche", "kg", 38.0, 3, 10),
    ("Cecina", "kg", 30.0, 3, 8), ("Chorizo regional", "kg", 26.0, 2, 6), ("Limón", "kg", 6.0, 6, 20),
    ("Cebolla roja", "kg", 3.5, 5, 15), ("Arroz", "kg", 4.2, 10, 30), ("Plátano verde", "u", 0.8, 30, 80),
    ("Camote", "kg", 2.5, 4, 10), ("Choclo", "u", 1.5, 15, 40), ("Yuca", "kg", 2.0, 4, 12),
    ("Aceite", "l", 9.0, 4, 12), ("Pulpa de camu camu", "kg", 12.0, 2, 6),
]
# nombre, categoría, precio, color, receta {insumo: cantidad por plato}
PLATOS = [
    ("Ceviche de pescado", "Ceviches", 32, "#2e8b74", {"Pescado fresco": .25, "Limón": .15, "Cebolla roja": .08, "Camote": .1, "Choclo": .5}),
    ("Ceviche mixto", "Ceviches", 38, "#2e8b74", {"Pescado fresco": .15, "Mariscos mixtos": .12, "Limón": .15, "Cebolla roja": .08, "Camote": .1, "Choclo": .5}),
    ("Leche de tigre", "Ceviches", 18, "#2e8b74", {"Pescado fresco": .1, "Mariscos mixtos": .05, "Limón": .12, "Cebolla roja": .03}),
    ("Tiradito de paiche", "Ceviches", 36, "#2e8b74", {"Paiche": .2, "Limón": .12}),
    ("Chicharrón de pescado", "Fritos", 34, "#b8862b", {"Pescado fresco": .3, "Yuca": .2, "Aceite": .1, "Limón": .03}),
    ("Jalea mixta", "Fritos", 42, "#b8862b", {"Pescado fresco": .2, "Mariscos mixtos": .15, "Yuca": .2, "Aceite": .15, "Cebolla roja": .05}),
    ("Paiche frito con tacacho", "Fritos", 45, "#b8862b", {"Paiche": .25, "Plátano verde": 2, "Aceite": .1}),
    ("Arroz con mariscos", "Arroces", 36, "#a8552f", {"Arroz": .15, "Mariscos mixtos": .2, "Cebolla roja": .04, "Aceite": .03}),
    ("Chaufa de mariscos", "Arroces", 34, "#a8552f", {"Arroz": .2, "Mariscos mixtos": .15, "Aceite": .04}),
    ("Tacacho con cecina y chorizo", "Amazónicos", 30, "#7c5a9e", {"Plátano verde": 3, "Cecina": .2, "Chorizo regional": .1, "Aceite": .05}),
    ("Patarashca de pescado", "Amazónicos", 35, "#7c5a9e", {"Pescado fresco": .35, "Cebolla roja": .05, "Yuca": .2}),
    ("Refresco de camu camu (jarra)", "Bebidas", 15, "#3b7bb0", {"Pulpa de camu camu": .15}),
    ("Chicha morada (jarra)", "Bebidas", 12, "#3b7bb0", {}),
    ("Cerveza", "Bebidas", 9, "#3b7bb0", {}),
]
# nombre, puesto, jornal diario, días desde el último pago, ¿tiene alta en T-Registro?
PERSONAL = {
    "A": [("Carlos Pinedo", "Cocinero jefe", 80, 13, 1), ("Lucía Ríos", "Cajera", 60, 13, 1),
          ("Jhon Tapullima", "Mozo", 50, 6, 1), ("Kelly Vásquez", "Mozo", 50, 13, 1),
          ("Brayan Ahuanari", "Ayudante de cocina", 55, 6, 1), ("Milagros Pezo", "Mozo", 50, 9, 1),
          ("Josué Arévalo", "Repartidor", 45, 4, 1), ("Diana Shapiama", "Ayudante de cocina", 55, 9, 1)],
    "B": [("Marco Del Águila", "Cocinero jefe", 80, 13, 1), ("Yessica Torres", "Cajera", 60, 13, 1),
          ("Kevin Isuiza", "Mozo", 50, 6, 1), ("Angie Flores", "Mozo", 50, 9, 1),
          ("Renzo Saldaña", "Ayudante de cocina", 55, 13, 1), ("Pamela Huaymacari", "Mozo", 50, 5, 0),
          ("Jair Panduro", "Repartidor", 45, 6, 1)],
    "C": [("Edwin Ramírez", "Cocinero", 75, 9, 1), ("Sandra Lozano", "Cajera", 60, 9, 1),
          ("Erick Mozombite", "Mozo", 50, 3, 0), ("Fiorella Macedo", "Mozo", 50, 9, 1),
          ("Luis Yumbato", "Ayudante de cocina", 55, 9, 1)],
}
MOZOS = {"A": ["Jhon", "Kelly", "Milagros"], "B": ["Kevin", "Angie", "Pamela"], "C": ["Erick", "Fiorella"]}
VENTAS_SEMILLA = {"A": 26, "B": 20, "C": 8}
BAJOS_SEMILLA = {"A": ["Limón", "Mariscos mixtos"], "B": ["Pescado fresco", "Pulpa de camu camu", "Cebolla roja"],
                 "C": ["Paiche"]}


def ahora() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def hoy() -> date:
    return datetime.now(LIMA).date()


def fecha_de(dt: datetime) -> str:
    return dt.astimezone(LIMA).date().isoformat()


def r2(x: float) -> float:
    return round(x + 1e-9, 2)


# ------------------------------------------------------------------ lógica de negocio
def necesidades(c, items) -> dict[int, float]:
    """Insumos que consume una lista de (plato_id, cant)."""
    nec: dict[int, float] = {}
    for pid, cant in items:
        for r in c.execute("SELECT insumo_id, cant FROM receta WHERE plato_id=?", (pid,)):
            nec[r["insumo_id"]] = nec.get(r["insumo_id"], 0) + r["cant"] * cant
    return nec


def descontar(c, local_id: int, nec: dict, ts: datetime, ref: str) -> None:
    for iid, q in nec.items():
        c.execute("UPDATE stock SET cant=MAX(cant-?,0) WHERE local_id=? AND insumo_id=?", (q, local_id, iid))
        c.execute("INSERT INTO mov_insumo(ts,fecha,local_id,insumo_id,cant,tipo,ref) VALUES(?,?,?,?,?,?,?)",
                  (iso(ts), fecha_de(ts), local_id, iid, q, "consumo", ref))


def siguiente_numero(c, local) -> str:
    n = c.execute("SELECT COUNT(*) FROM pedidos WHERE local_id=? AND fecha=?", (local["id"], hoy().isoformat())).fetchone()[0]
    return f"{local['letra']}-{n + 1:03d}"


def emitir_comprobante(c, local) -> str:
    n = c.execute("SELECT COUNT(*) FROM pedidos WHERE local_id=? AND comprobante IS NOT NULL", (local["id"],)).fetchone()[0]
    return f"{local['serie']}-{local['base'] + n + 1:06d}"


def crear_pedido(c, local, tipo, items, ts, mozo, mesa=None, cliente=None, direccion=None):
    numero = siguiente_numero(c, local)
    precios = {p["id"]: p["precio"] for p in c.execute("SELECT id, precio FROM platos")}
    total = r2(sum(precios[pid] * q for pid, q in items))
    pid_ = c.execute("""INSERT INTO pedidos(local_id,numero,tipo,mesa,cliente,direccion,mozo,estado,creado,total,fecha)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                     (local["id"], numero, tipo, mesa, cliente, direccion, mozo, "cocina", iso(ts), total, fecha_de(ts))).lastrowid
    for p, q in items:
        c.execute("INSERT INTO items VALUES(?,?,?,?)", (pid_, p, q, precios[p]))
    descontar(c, local["id"], necesidades(c, items), ts, numero)
    return pid_, numero, total


def sembrar(c) -> None:
    rnd = random.Random(20261102)
    for t in ("mov_insumo", "items", "pedidos", "pagos", "asistencia", "personal", "receta", "platos", "stock",
              "insumos", "locales"):
        c.execute(f"DELETE FROM {t}")
    for letra, nombre, sub, serie, base in LOCALES:
        c.execute("INSERT INTO locales(letra,nombre,sub,serie,base) VALUES(?,?,?,?,?)", (letra, nombre, sub, serie, base))
    locales = {r["letra"]: r for r in c.execute("SELECT * FROM locales")}
    for nombre, unidad, costo, mn, obj in INSUMOS:
        iid = c.execute("INSERT INTO insumos(nombre,unidad,costo) VALUES(?,?,?)", (nombre, unidad, costo)).lastrowid
        for letra, loc in locales.items():
            k = ESCALA_LOCAL[letra]
            c.execute("INSERT INTO stock VALUES(?,?,?,?,?)",
                      (loc["id"], iid, round(obj * k * rnd.uniform(.75, 1.0), 2), round(mn * k, 1), round(obj * k, 1)))
    ins = {r["nombre"]: r["id"] for r in c.execute("SELECT id, nombre FROM insumos")}
    for nombre, cat, precio, color, rec in PLATOS:
        pid = c.execute("INSERT INTO platos(nombre,cat,precio,color) VALUES(?,?,?,?)", (nombre, cat, precio, color)).lastrowid
        for i, q in rec.items():
            c.execute("INSERT INTO receta VALUES(?,?,?)", (pid, ins[i], q))
    platos = [dict(r) for r in c.execute("SELECT * FROM platos")]
    peso = {"Ceviche de pescado": 9, "Ceviche mixto": 7, "Chicharrón de pescado": 6, "Jalea mixta": 4,
            "Leche de tigre": 4, "Arroz con mariscos": 4, "Tacacho con cecina y chorizo": 3, "Chaufa de mariscos": 3,
            "Patarashca de pescado": 2, "Tiradito de paiche": 2, "Paiche frito con tacacho": 2,
            "Refresco de camu camu (jarra)": 6, "Chicha morada (jarra)": 5, "Cerveza": 6}

    # Personal, asistencia de días previos y adelantos
    h = hoy()
    ahora_lima = datetime.now(LIMA)
    for letra, lista in PERSONAL.items():
        loc = locales[letra]
        for nombre, puesto, jornal, dias, treg in lista:
            desde = h - timedelta(days=dias)
            per = c.execute("INSERT INTO personal(local_id,nombre,puesto,jornal,desde,t_registro) VALUES(?,?,?,?,?,?)",
                            (loc["id"], nombre, puesto, jornal, desde.isoformat(), treg)).lastrowid
            for d in range(1, dias):
                dia = desde + timedelta(days=d)
                falta = rnd.random() < (0.38 if dia.weekday() == 6 else 0.06)
                if not falta:
                    ent = datetime.combine(dia, time(9, rnd.randint(0, 50)), LIMA)
                    sal = datetime.combine(dia, time(17, rnd.randint(0, 59)), LIMA)
                    c.execute("INSERT INTO asistencia(personal_id,fecha,entrada,salida) VALUES(?,?,?,?)",
                              (per, dia.isoformat(), iso(ent), iso(sal)))
            if dias > 5 and rnd.random() < 0.45:
                c.execute("INSERT INTO pagos(personal_id,fecha,ts,monto,tipo) VALUES(?,?,?,?,?)",
                          (per, (desde + timedelta(days=3)).isoformat(), iso(ahora()), rnd.choice([50, 80, 100]), "adelanto"))
            # Hoy: la mayoría ya marcó entrada (si ya es hora)
            ent_hoy = datetime.combine(h, time(9, rnd.randint(0, 45)), LIMA)
            if ent_hoy < ahora_lima and rnd.random() < 0.82:
                c.execute("INSERT INTO asistencia(personal_id,fecha,entrada) VALUES(?,?,?)", (per, h.isoformat(), iso(ent_hoy)))

    # Ventas de hoy (antes de ahora) para que el panel muestre el día en curso
    inicio_dia = datetime.combine(h, time(0, 5), LIMA)
    ventana = max(20, min(330, int((ahora_lima - inicio_dia).total_seconds() // 60) - 5))
    metodos = ["efectivo"] * 35 + ["yape"] * 45 + ["tarjeta"] * 20
    for letra, n in VENTAS_SEMILLA.items():
        loc = locales[letra]
        marcas = sorted((rnd.randint(4, ventana) for _ in range(n)), reverse=True)
        for k, mins in enumerate(marcas):
            ts = ahora() - timedelta(minutes=mins)
            items = {}
            for _ in range(rnd.randint(1, 4)):
                p = rnd.choices(platos, weights=[peso[x["nombre"]] for x in platos])[0]
                items[p["id"]] = items.get(p["id"], 0) + rnd.choice([1, 1, 1, 2])
            tipo = "delivery" if rnd.random() < 0.2 else "mesa"
            pid, numero, total = crear_pedido(
                c, loc, tipo, list(items.items()), ts, rnd.choice(MOZOS[letra]),
                mesa=str(rnd.randint(1, 14)) if tipo == "mesa" else None,
                cliente=rnd.choice(["Sra. Pérez", "Jorge M.", "Oficina Petroperú", "Ana L.", "Sr. Ruiz"]) if tipo == "delivery" else None,
                direccion=rnd.choice(["Jr. Próspero 512", "Av. Quiñones km 3", "Calle Putumayo 240", "Jr. Arica 815"]) if tipo == "delivery" else None)
            restantes = n - k
            if restantes <= (2 if letra != "C" else 1):          # los últimos siguen en cocina
                continue
            listo = ts + timedelta(minutes=rnd.randint(8, 18))
            if restantes <= (3 if letra != "C" else 1) and listo < ahora():   # listo, por cobrar
                c.execute("UPDATE pedidos SET estado='listo', listo=? WHERE id=?", (iso(listo), pid))
                continue
            pagado = min(listo + timedelta(minutes=rnd.randint(10, 35)), ahora() - timedelta(minutes=1))
            comp = emitir_comprobante(c, loc)
            c.execute("""UPDATE pedidos SET estado='pagado', listo=?, pagado=?, metodo=?, comprobante=?, comp_estado='aceptado'
                         WHERE id=?""", (iso(listo), iso(pagado), rnd.choice(metodos), comp, pid))
    # Un delivery en camino en el Local A
    d = c.execute("SELECT id FROM pedidos WHERE local_id=? AND estado='listo' LIMIT 1", (locales["A"]["id"],)).fetchone()
    if d:
        c.execute("UPDATE pedidos SET tipo='delivery', mesa=NULL, cliente='Sra. Pérez', direccion='Jr. Próspero 512', "
                  "estado='en_camino', despachado=? WHERE id=?", (iso(ahora() - timedelta(minutes=6)), d["id"]))
    # Estados de comprobantes para el contador
    r = c.execute("SELECT id FROM pedidos WHERE local_id=? AND comprobante IS NOT NULL ORDER BY id LIMIT 1 OFFSET 3",
                  (locales["B"]["id"],)).fetchone()
    if r:
        c.execute("UPDATE pedidos SET comp_estado='rechazado' WHERE id=?", (r["id"],))
    r = c.execute("SELECT id FROM pedidos WHERE local_id=? AND comprobante IS NOT NULL ORDER BY id DESC LIMIT 1",
                  (locales["A"]["id"],)).fetchone()
    if r:
        c.execute("UPDATE pedidos SET comp_estado='enviando' WHERE id=?", (r["id"],))

    # Stock: algunos insumos quedan bajos a propósito, el resto por encima del mínimo
    for letra, loc in locales.items():
        for s in c.execute("SELECT s.*, i.nombre FROM stock s JOIN insumos i ON i.id=s.insumo_id WHERE local_id=?",
                           (loc["id"],)).fetchall():
            if s["nombre"] in BAJOS_SEMILLA[letra]:
                nuevo = round(s["minimo"] * rnd.uniform(.35, .7), 2)
            elif s["cant"] < s["minimo"] * 1.3:
                nuevo = round(s["minimo"] * rnd.uniform(1.4, 2.2), 2)
            else:
                continue
            c.execute("UPDATE stock SET cant=? WHERE local_id=? AND insumo_id=?", (nuevo, loc["id"], s["insumo_id"]))


def iniciar_db() -> None:
    with _lock:
        _conn.executescript(ESQUEMA)
        if _conn.execute("SELECT COUNT(*) FROM locales").fetchone()[0] == 0:
            sembrar(_conn)
        _conn.commit()


def liquidacion(c, per, h: date) -> dict:
    desde = date.fromisoformat(per["desde"])
    dias = c.execute("SELECT COUNT(*) FROM asistencia WHERE personal_id=? AND fecha>? AND entrada IS NOT NULL",
                     (per["id"], desde.isoformat())).fetchone()[0]
    previos = max((h - desde).days - 1, 0)
    asistidos_previos = c.execute("SELECT COUNT(*) FROM asistencia WHERE personal_id=? AND fecha>? AND fecha<?",
                                  (per["id"], desde.isoformat(), h.isoformat())).fetchone()[0]
    adelantos = c.execute("SELECT COALESCE(SUM(monto),0) FROM pagos WHERE personal_id=? AND tipo='adelanto' AND fecha>?",
                          (per["id"], desde.isoformat())).fetchone()[0]
    hoy_a = c.execute("SELECT entrada, salida FROM asistencia WHERE personal_id=? AND fecha=?",
                      (per["id"], h.isoformat())).fetchone()
    return {"dias": dias, "faltas": max(previos - asistidos_previos, 0), "adelantos": r2(adelantos),
            "devengado": r2(dias * per["jornal"]), "por_pagar": r2(dias * per["jornal"] - adelantos),
            "entrada": hoy_a["entrada"] if hoy_a else None, "salida": hoy_a["salida"] if hoy_a else None}


def estado_completo() -> dict:
    c = _conn
    h = hoy().isoformat()
    insumos = {r["id"]: dict(r) for r in c.execute("SELECT * FROM insumos ORDER BY id")}
    platos = [dict(p) for p in c.execute("SELECT * FROM platos ORDER BY id")]
    recetas = {}
    for r in c.execute("SELECT * FROM receta"):
        recetas.setdefault(r["plato_id"], []).append((r["insumo_id"], r["cant"]))
    for p in platos:
        p["receta"] = [[insumos[i]["nombre"], q, insumos[i]["unidad"]] for i, q in recetas.get(p["id"], [])]

    locales = []
    for loc in c.execute("SELECT * FROM locales ORDER BY id").fetchall():
        lid = loc["id"]
        stock = {s["insumo_id"]: dict(s) for s in c.execute("SELECT * FROM stock WHERE local_id=?", (lid,))}
        # porciones disponibles por plato
        disp = {}
        for p in platos:
            rec = recetas.get(p["id"], [])
            disp[p["id"]] = None if not rec else int(min(math.floor(stock[i]["cant"] / q + 1e-9) for i, q in rec))
        peds = [dict(p) for p in c.execute("SELECT * FROM pedidos WHERE local_id=? AND fecha=? ORDER BY id", (lid, h))]
        for p in peds:
            p["items"] = [dict(i) for i in c.execute(
                "SELECT i.plato_id, i.cant, i.precio, pl.nombre FROM items i JOIN platos pl ON pl.id=i.plato_id WHERE pedido_id=?",
                (p["id"],))]
        pagados = [p for p in peds if p["estado"] == "pagado"]
        por_metodo = {m: r2(sum(p["total"] for p in pagados if p["metodo"] == m)) for m in ("efectivo", "yape", "tarjeta")}
        vendidos: dict[int, list] = {}
        for p in peds:
            for i in p["items"]:
                v = vendidos.setdefault(i["plato_id"], [i["nombre"], 0, 0.0])
                v[1] += i["cant"]
                v[2] += i["cant"] * i["precio"]
        top = sorted(vendidos.values(), key=lambda x: (-x[1], x[0]))
        consumo = []
        for r in c.execute("""SELECT insumo_id, SUM(cant) q FROM mov_insumo WHERE local_id=? AND fecha=? AND tipo='consumo'
                               GROUP BY insumo_id ORDER BY q DESC""", (lid, h)):
            ins = insumos[r["insumo_id"]]
            consumo.append([ins["nombre"], round(r["q"], 2), ins["unidad"], r2(r["q"] * ins["costo"])])
        consumo.sort(key=lambda x: -x[3])
        bajos, compras = [], []
        for iid, s in stock.items():
            ins = insumos[iid]
            if s["cant"] < s["minimo"]:
                bajos.append([ins["nombre"], round(s["cant"], 2), s["minimo"], ins["unidad"]])
                q = math.ceil((s["objetivo"] - s["cant"]) * 10) / 10
                compras.append({"insumo_id": iid, "insumo": ins["nombre"], "unidad": ins["unidad"], "queda": round(s["cant"], 2),
                                "minimo": s["minimo"], "comprar": q, "costo": r2(q * ins["costo"])})
        personal = []
        for per in c.execute("SELECT * FROM personal WHERE local_id=? ORDER BY id", (lid,)).fetchall():
            personal.append({**dict(per), **liquidacion(c, per, hoy())})
        asistieron = [p for p in personal if p["entrada"]]
        locales.append({
            "id": lid, "letra": loc["letra"], "nombre": loc["nombre"], "sub": loc["sub"], "serie": loc["serie"],
            "ventas": r2(sum(p["total"] for p in pagados)), "por_metodo": por_metodo, "atendidos": len(pagados),
            "ticket": r2(sum(p["total"] for p in pagados) / len(pagados)) if pagados else 0,
            "en_cocina": sum(1 for p in peds if p["estado"] == "cocina"),
            "por_cobrar": r2(sum(p["total"] for p in peds if p["estado"] in ("listo", "en_camino"))),
            "delivery": sum(1 for p in peds if p["tipo"] == "delivery"),
            "top": [[n, q, r2(m)] for n, q, m in top[:5]],
            "consumo": consumo, "costo_insumos": r2(sum(x[3] for x in consumo)),
            "bajos": sorted(bajos, key=lambda b: b[1] / b[2]), "compras": compras,
            "stock": [{"insumo": insumos[i]["nombre"], "unidad": insumos[i]["unidad"], "cant": round(s["cant"], 2),
                       "minimo": s["minimo"], "objetivo": s["objetivo"]} for i, s in sorted(stock.items())],
            "disp": disp, "pedidos": peds, "personal": personal,
            "asistieron": len(asistieron), "total_personal": len(personal),
            "faltan": [p["nombre"] for p in personal if not p["entrada"]],
            "por_pagar": r2(sum(p["por_pagar"] for p in personal)),
        })
    comprobantes = [dict(r) for r in c.execute(
        """SELECT p.comprobante, p.comp_estado, p.total, p.pagado, p.metodo, l.nombre AS local FROM pedidos p
           JOIN locales l ON l.id=p.local_id WHERE p.comprobante IS NOT NULL ORDER BY p.pagado DESC""")]
    return {"locales": locales, "platos": platos, "comprobantes": comprobantes, "hoy": h, "servidor": iso(ahora())}


# ------------------------------------------------------------------ tiempo real (SSE)
clientes: set[asyncio.Queue] = set()


def difundir(evento: dict) -> None:
    for q in list(clientes):
        try:
            q.put_nowait(evento)
        except asyncio.QueueFull:
            pass


async def eventos(request: Request):
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    clientes.add(q)

    async def flujo():
        try:
            yield "retry: 2000\n\n"
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": latido\n\n"
        finally:
            clientes.discard(q)

    return StreamingResponse(flujo(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ API
def soles(x: float) -> str:
    return f"S/ {x:,.2f}"


def error(msg: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=code)


def get_local(c, local_id):
    return c.execute("SELECT * FROM locales WHERE id=?", (local_id,)).fetchone()


async def api_estado(request: Request):
    with _lock:
        return JSONResponse(estado_completo())


async def api_pedido(request: Request):
    d = await request.json()
    items = {}
    for i in d.get("items", []):
        q = int(i.get("cant", 0))
        if q > 0:
            items[int(i["plato_id"])] = items.get(int(i["plato_id"]), 0) + q
    if not items:
        return error("Agrega al menos un plato.")
    tipo = d.get("tipo") if d.get("tipo") in ("mesa", "delivery", "llevar") else "mesa"
    mesa = str(d.get("mesa") or "").strip()[:6]
    cliente = str(d.get("cliente") or "").strip()[:40]
    direccion = str(d.get("direccion") or "").strip()[:60]
    if tipo == "mesa" and not mesa:
        return error("Elige el número de mesa.")
    if tipo == "delivery" and (not cliente or not direccion):
        return error("Para delivery escribe el nombre del cliente y la dirección.")
    with _lock:
        c = _conn
        local = get_local(c, d.get("local_id"))
        if not local:
            return error("Local no encontrado.", 404)
        for iid, q in necesidades(c, list(items.items())).items():
            s = c.execute("SELECT s.cant, i.nombre, i.unidad FROM stock s JOIN insumos i ON i.id=s.insumo_id "
                          "WHERE local_id=? AND insumo_id=?", (local["id"], iid)).fetchone()
            if s["cant"] + 1e-9 < q:
                return error(f"No alcanza {s['nombre']}: quedan {s['cant']:.2f} {s['unidad']} y este pedido necesita "
                             f"{q:.2f}. Avisa al cliente o cambia el plato.", 409)
        pid, numero, total = crear_pedido(c, local, tipo, list(items.items()), ahora(),
                                          str(d.get("mozo") or "Mozo")[:20], mesa or None, cliente or None, direccion or None)
        c.commit()
        nombres = dict(c.execute("SELECT id, nombre FROM platos").fetchall())
    donde = f"Mesa {mesa}" if tipo == "mesa" else ("Delivery · " + cliente if tipo == "delivery" else "Para llevar")
    detalle = ", ".join(f"{q} {nombres[p]}" for p, q in items.items())
    difundir({"tipo": "pedido_nuevo", "local_id": local["id"], "numero": numero,
              "texto": f"{local['nombre']} · {numero} · {donde}: {detalle}"})
    return JSONResponse({"ok": True, "numero": numero, "total": total})


async def api_accion(request: Request):
    pid = int(request.path_params["pid"])
    accion = request.path_params["accion"]
    d = await request.json() if accion == "cobrar" else {}
    with _lock:
        c = _conn
        p = c.execute("SELECT * FROM pedidos WHERE id=?", (pid,)).fetchone()
        if not p:
            return error("Pedido no encontrado.", 404)
        local = get_local(c, p["local_id"])
        donde = f"Mesa {p['mesa']}" if p["tipo"] == "mesa" else ("Delivery · " + (p["cliente"] or "") if p["tipo"] == "delivery" else "Para llevar")
        if accion == "listo":
            if p["estado"] != "cocina":
                return error(f"El pedido {p['numero']} ya salió de cocina.", 409)
            c.execute("UPDATE pedidos SET estado='listo', listo=? WHERE id=?", (iso(ahora()), pid))
            texto = f"{p['numero']} · {donde} está listo" + (" para enviar." if p["tipo"] == "delivery" else " para servir.")
        elif accion == "despachar":
            if p["estado"] != "listo" or p["tipo"] != "delivery":
                return error("Solo se despacha un delivery que ya está listo.", 409)
            c.execute("UPDATE pedidos SET estado='en_camino', despachado=? WHERE id=?", (iso(ahora()), pid))
            texto = f"{p['numero']} salió con el repartidor a {p['direccion']}."
        elif accion == "cobrar":
            metodo = d.get("metodo")
            if metodo not in ("efectivo", "yape", "tarjeta"):
                return error("Elige cómo pagó el cliente.")
            if p["estado"] not in ("listo", "en_camino"):
                return error(f"El pedido {p['numero']} no está pendiente de cobro.", 409)
            comp = emitir_comprobante(c, local)
            c.execute("UPDATE pedidos SET estado='pagado', pagado=?, metodo=?, comprobante=?, comp_estado='aceptado' WHERE id=?",
                      (iso(ahora()), metodo, comp, pid))
            nombre_m = {"efectivo": "efectivo", "yape": "Yape/Plin", "tarjeta": "tarjeta"}[metodo]
            texto = f"{local['nombre']} cobró {soles(p['total'])} en {nombre_m} · {p['numero']} · boleta {comp}"
        else:
            return error("Acción no válida.")
        c.commit()
    difundir({"tipo": accion, "local_id": p["local_id"], "numero": p["numero"], "texto": texto})
    return JSONResponse({"ok": True})


async def api_asistencia(request: Request):
    d = await request.json()
    with _lock:
        c = _conn
        per = c.execute("SELECT * FROM personal WHERE id=?", (d.get("personal_id"),)).fetchone()
        if not per:
            return error("Trabajador no encontrado.", 404)
        h = hoy().isoformat()
        a = c.execute("SELECT * FROM asistencia WHERE personal_id=? AND fecha=?", (per["id"], h)).fetchone()
        if not a:
            c.execute("INSERT INTO asistencia(personal_id,fecha,entrada) VALUES(?,?,?)", (per["id"], h, iso(ahora())))
            texto = f"{per['nombre']} marcó entrada."
        elif not a["salida"]:
            c.execute("UPDATE asistencia SET salida=? WHERE id=?", (iso(ahora()), a["id"]))
            texto = f"{per['nombre']} marcó salida."
        else:
            return error(f"{per['nombre']} ya marcó entrada y salida hoy.", 409)
        c.commit()
    difundir({"tipo": "asistencia", "local_id": per["local_id"], "texto": texto})
    return JSONResponse({"ok": True})


async def api_pago(request: Request):
    per_id = int(request.path_params["per"])
    d = await request.json()
    with _lock:
        c = _conn
        per = c.execute("SELECT * FROM personal WHERE id=?", (per_id,)).fetchone()
        if not per:
            return error("Trabajador no encontrado.", 404)
        liq = liquidacion(c, per, hoy())
        h = hoy().isoformat()
        if d.get("tipo") == "adelanto":
            try:
                monto = round(float(d.get("monto", 0)), 2)
            except (TypeError, ValueError):
                monto = 0
            if monto <= 0:
                return error("Escribe el monto del adelanto.")
            if monto > liq["por_pagar"]:
                return error(f"El adelanto supera lo que se le debe ({soles(liq['por_pagar'])}).")
            c.execute("INSERT INTO pagos(personal_id,fecha,ts,monto,tipo) VALUES(?,?,?,?,?)", (per_id, h, iso(ahora()), monto, "adelanto"))
            texto = f"Adelanto de {soles(monto)} a {per['nombre']}."
        else:
            if liq["por_pagar"] <= 0:
                return error(f"No hay saldo pendiente con {per['nombre']}.")
            c.execute("INSERT INTO pagos(personal_id,fecha,ts,monto,tipo) VALUES(?,?,?,?,?)",
                      (per_id, h, iso(ahora()), liq["por_pagar"], "liquidacion"))
            c.execute("UPDATE personal SET desde=? WHERE id=?", (h, per_id))
            texto = f"Se pagaron {soles(liq['por_pagar'])} a {per['nombre']} ({liq['dias']} días). Saldo en cero."
        c.commit()
    difundir({"tipo": "pago", "local_id": per["local_id"], "texto": texto})
    return JSONResponse({"ok": True})


async def api_compra(request: Request):
    d = await request.json()
    with _lock:
        c = _conn
        local = get_local(c, d.get("local_id"))
        if not local:
            return error("Local no encontrado.", 404)
        filas = c.execute("SELECT s.*, i.nombre FROM stock s JOIN insumos i ON i.id=s.insumo_id WHERE local_id=? AND cant<minimo",
                          (local["id"],)).fetchall()
        if not filas:
            return error(f"{local['nombre']} no tiene insumos por reponer.")
        ts = ahora()
        for s in filas:
            q = s["objetivo"] - s["cant"]
            c.execute("UPDATE stock SET cant=objetivo WHERE local_id=? AND insumo_id=?", (local["id"], s["insumo_id"]))
            c.execute("INSERT INTO mov_insumo(ts,fecha,local_id,insumo_id,cant,tipo,ref) VALUES(?,?,?,?,?,?,?)",
                      (iso(ts), fecha_de(ts), local["id"], s["insumo_id"], q, "compra", "Compra"))
        c.commit()
    difundir({"tipo": "compra", "local_id": local["id"],
              "texto": f"{local['nombre']} repuso {len(filas)} insumo(s): " + ", ".join(s["nombre"] for s in filas)})
    return JSONResponse({"ok": True})


async def api_reset(request: Request):
    with _lock:
        sembrar(_conn)
        _conn.commit()
    difundir({"tipo": "reinicio", "texto": "La demo volvió a los datos iniciales del día."})
    return JSONResponse({"ok": True})


def pagina(nombre: str):
    async def vista(request: Request):
        try:
            local = int(request.query_params.get("l", "1"))
        except ValueError:
            local = 1
        return templates.TemplateResponse(request, nombre, {"local_id": local if local in (1, 2, 3) else 1})
    return vista


async def salud(request: Request):
    return JSONResponse({"ok": True})


rutas = [
    Route("/", pagina("inicio.html")),
    Route("/mozo", pagina("mozo.html")),
    Route("/cocina", pagina("cocina.html")),
    Route("/caja", pagina("caja.html")),
    Route("/personal", pagina("personal.html")),
    Route("/duenos", pagina("duenos.html")),
    Route("/contador", pagina("contador.html")),
    Route("/panel", pagina("panel.html")),
    Route("/eventos", eventos),
    Route("/api/estado", api_estado),
    Route("/api/pedidos", api_pedido, methods=["POST"]),
    Route("/api/pedidos/{pid:int}/{accion}", api_accion, methods=["POST"]),
    Route("/api/asistencia", api_asistencia, methods=["POST"]),
    Route("/api/personal/{per:int}/pago", api_pago, methods=["POST"]),
    Route("/api/compras", api_compra, methods=["POST"]),
    Route("/api/reiniciar", api_reset, methods=["POST"]),
    Route("/salud", salud),
    Mount("/static", StaticFiles(directory=str(BASE / "static")), name="static"),
]

iniciar_db()
app = Starlette(routes=rutas)
