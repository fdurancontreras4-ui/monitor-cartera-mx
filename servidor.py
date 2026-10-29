#!/usr/bin/env python3
"""
Servidor del Monitor de Cartera MX para Replit.

Sirve el mismo index.html que GitHub Pages, pero dos archivos se arman en vivo
cada vez que el tablero los pide (o sea, cada vez que alguien pulsa
"↻ Recargar datos"):

    /cartera.xlsx   → "Cuentas Postventa.xlsx" bajado de OneDrive (Microsoft Graph)
    /deals-mx.json  → deals de Zoho CRM (KAM México · Dafne / Raúl / Karla)

Mientras no haya credenciales de Microsoft (TI todavía no registra la app),
la cartera llega por otro camino: la Mac de Fernanda, que tiene OneDrive
sincronizado, sube el Excel a POST /api/cartera cada vez que cambia
(scripts/sincronizar-cartera-mac.py). El servidor sirve esa copia.

Si falta una credencial o la fuente falla, responde con el archivo que está en
el repo y lo marca con el encabezado `X-Fuente: respaldo`, así el tablero nunca
queda en blanco. /api/estado dice qué está configurado y cuándo fue la última
lectura buena de cada fuente.

Todas las credenciales vienen de variables de entorno (Secrets de Replit),
nunca del repo:

    TABLERO_CLAVE        contraseña para entrar al tablero (si no está, queda abierto)
    MS_TENANT_ID         Entra ID de GeoVictoria (Directory/tenant ID)
    MS_CLIENT_ID         Application (client) ID de la app registrada
    MS_REFRESH_TOKEN     refresh token de Fernanda (scripts/obtener-tokens.py microsoft)
    ZOHO_CLIENT_ID       Self Client de api-console.zoho.com
    ZOHO_CLIENT_SECRET
    ZOHO_REFRESH_TOKEN   (scripts/obtener-tokens.py zoho)

    CARTERA_SUBIDA_CLAVE clave que usa la Mac para subir el Excel (sin ella, la subida está apagada)

Opcionales: POSTVENTA_DRIVE_ID / POSTVENTA_ITEM_ID (si el archivo se mueve),
ZOHO_ACCOUNTS_URL / ZOHO_API_URL (otro datacenter), CACHE_SEGUNDOS, PORT.

Solo usa la librería estándar de Python 3 — no hay que instalar nada.
"""

import base64
import datetime as dt
import hashlib
import hmac
import zipfile
import io
import importlib.util
import json
import mimetypes
import os
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
ENV = os.environ.get

# Archivo real de Cuentas Postventa (ver la skill postventa-mrr: nunca usar una copia de búsqueda)
DRIVE_ID = ENV("POSTVENTA_DRIVE_ID", "b!sAG5r_bfbEGvk01PB7t4cQzL2hbo70NNv2KSjMR1GulyjRiY0B71TJsImZRJSNRV")
ITEM_ID = ENV("POSTVENTA_ITEM_ID", "01FBJR3VU6WJGDP3GGFZHL6WFG5C5WDSPN")

ZOHO_ACCOUNTS = ENV("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com").rstrip("/")
ZOHO_API = ENV("ZOHO_API_URL", "https://www.zohoapis.com").rstrip("/")
ZOHO_FIELDS = ("id,Deal_Name,Account_Name,KAM,Owner,Territorio,Stage,Producto_Soluci_n,"
               "Valor_del_trato_Global,Correo_KAM,Created_Time,Modified_Time,"
               "Mes_cierre_Cross_UP,Tipo_Trato,Monda_del_trato,N_Empleados_que_marcan,Valor_por_usuario_Global")

CACHE_SEGUNDOS = int(ENV("CACHE_SEGUNDOS", "60"))
TIMEOUT = 60

# Reutiliza la forma y el criterio de scripts/subir-deals-zoho.py, para que el
# deals-mx.json en vivo sea idéntico al que publica el script.
_spec = importlib.util.spec_from_file_location("subir_deals", RAIZ / "scripts" / "subir-deals-zoho.py")
SD = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SD)
ZOHO_CRITERIA = "((Owner:equals:{})and({}))".format(
    SD.KAM_OWNER_ID, "or".join(f"(KAM:equals:{k})" for k in SD.KAMS_VALIDOS))

# Lo que se puede servir desde el repo. Todo lo demás (scripts, .git, .claude…) es 404.
EXT_PUBLICAS = {".html", ".json", ".xlsx", ".csv", ".png", ".jpg", ".svg", ".ico", ".js", ".css"}

ESTADO = {"cartera": {}, "deals": {}}
_cache = {}
_locks = {"cartera": threading.Lock(), "deals": threading.Lock()}
_tokens = {}

# Copia subida desde la Mac. Vive en disco mientras la instancia viva; si Replit
# la reinicia, la Mac la vuelve a mandar en su siguiente pasada (compara el hash).
DATOS = Path(ENV("DATOS_DIR", str(RAIZ / ".datos")))
SUBIDA = DATOS / "cartera-subida.xlsx"
SUBIDA_META = DATOS / "cartera-subida.json"
TAM_MAX_SUBIDA = 15 * 1024 * 1024


def ahora_iso():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


class FuenteError(Exception):
    """Error esperable de una fuente, con un mensaje que se puede mostrar."""


# ------------------------------------------------------------------ HTTP saliente

def pedir(url, data=None, headers=None, metodo=None):
    if isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def json_o_texto(cuerpo):
    try:
        return json.loads(cuerpo or b"{}")
    except ValueError:
        return {"texto": cuerpo[:300].decode("utf-8", "replace")}


# ------------------------------------------------------------------ Microsoft Graph

def token_microsoft():
    t = _tokens.get("ms")
    if t and t["vence"] > time.time() + 60:
        return t["access"]
    tenant, cliente = ENV("MS_TENANT_ID"), ENV("MS_CLIENT_ID")
    refresh = _tokens.get("ms_refresh") or ENV("MS_REFRESH_TOKEN")
    if not (tenant and cliente and refresh):
        raise FuenteError("Faltan MS_TENANT_ID, MS_CLIENT_ID o MS_REFRESH_TOKEN en los Secrets.")
    status, cuerpo = pedir(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        {"client_id": cliente, "grant_type": "refresh_token", "refresh_token": refresh,
         "scope": "offline_access Files.Read"})
    j = json_o_texto(cuerpo)
    if status != 200:
        raise FuenteError("Microsoft rechazó el refresh token ({}): {}. Genera uno nuevo con "
                          "scripts/obtener-tokens.py microsoft.".format(
                              j.get("error", status), (j.get("error_description") or "")[:160]))
    # Microsoft rota el refresh token: usamos el nuevo mientras el proceso viva.
    if j.get("refresh_token"):
        _tokens["ms_refresh"] = j["refresh_token"]
    _tokens["ms"] = {"access": j["access_token"], "vence": time.time() + int(j.get("expires_in", 3600))}
    return j["access_token"]


def leer_cartera():
    token = token_microsoft()
    url = f"https://graph.microsoft.com/v1.0/drives/{DRIVE_ID}/items/{ITEM_ID}/content"
    status, cuerpo = pedir(url, headers={"Authorization": f"Bearer {token}"})
    if status == 404:
        raise FuenteError("OneDrive no encuentra Cuentas Postventa.xlsx con ese itemId "
                          "(¿se movió o se recreó?). Actualiza POSTVENTA_ITEM_ID.")
    if status != 200:
        raise FuenteError(f"Microsoft Graph respondió HTTP {status}: {json_o_texto(cuerpo)}")
    if not cuerpo.startswith(b"PK"):
        raise FuenteError("Lo que bajó de OneDrive no es un .xlsx.")
    return cuerpo


# ------------------------------------------------------------------ Zoho CRM

def token_zoho():
    t = _tokens.get("zoho")
    if t and t["vence"] > time.time() + 60:
        return t["access"]
    cid, secreto, refresh = ENV("ZOHO_CLIENT_ID"), ENV("ZOHO_CLIENT_SECRET"), ENV("ZOHO_REFRESH_TOKEN")
    if not (cid and secreto and refresh):
        raise FuenteError("Faltan ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET o ZOHO_REFRESH_TOKEN en los Secrets.")
    status, cuerpo = pedir(f"{ZOHO_ACCOUNTS}/oauth/v2/token",
                           {"refresh_token": refresh, "client_id": cid, "client_secret": secreto,
                            "grant_type": "refresh_token"})
    j = json_o_texto(cuerpo)
    if status != 200 or "access_token" not in j:
        raise FuenteError("Zoho rechazó el refresh token ({}). Genera uno nuevo con "
                          "scripts/obtener-tokens.py zoho.".format(j.get("error", status)))
    _tokens["zoho"] = {"access": j["access_token"], "vence": time.time() + int(j.get("expires_in", 3600))}
    return j["access_token"]


def leer_deals():
    token = token_zoho()
    crudos = []
    for pagina in range(1, 11):  # searchRecords tope: 2.000 registros
        qs = urllib.parse.urlencode({"criteria": ZOHO_CRITERIA, "fields": ZOHO_FIELDS,
                                     "per_page": 200, "page": pagina})
        status, cuerpo = pedir(f"{ZOHO_API}/crm/v8/Deals/search?{qs}",
                               headers={"Authorization": f"Zoho-oauthtoken {token}"})
        if status == 204:
            break
        if status != 200:
            raise FuenteError(f"Zoho respondió HTTP {status}: {json_o_texto(cuerpo)}")
        j = json.loads(cuerpo)
        crudos.extend(j.get("data") or [])
        if not (j.get("info") or {}).get("more_records"):
            break

    # Mismas reglas que el script: solo KAM México y los tres KAM.
    crudos = [r for r in crudos
              if (r.get("Owner") or {}).get("name") == SD.KAM_OWNER_NOMBRE
              and (r.get("KAM") or "").strip() in SD.KAMS_VALIDOS]
    if not crudos:
        raise FuenteError("Zoho no devolvió deals con el criterio de KAM México.")
    vistos, deals = set(), []
    for r in crudos:
        d = SD.dar_forma(r)
        if d["id"] in vistos:
            continue
        vistos.add(d["id"])
        deals.append(d)
    deals.sort(key=lambda d: (d["kam"], SD.orden_etapa(d["etapa"]), -(d["valor"] or 0)))
    # módulos vendidos por comercial a clientes de la cartera (ver CRITERIO_COMERCIAL en el script);
    # si esta segunda búsqueda falla, el pipeline de KAM igual se sirve, sin la lista de comercial
    comercial = []
    try:
        qs = urllib.parse.urlencode({"criteria": SD.CRITERIO_COMERCIAL, "fields": ZOHO_FIELDS, "per_page": 200})
        status, cuerpo = pedir(f"{ZOHO_API}/crm/v8/Deals/search?{qs}",
                               headers={"Authorization": f"Zoho-oauthtoken {token}"})
        if status == 200:
            vistos_c = set()
            for r in json.loads(cuerpo).get("data") or []:
                if (r.get("Owner") or {}).get("id") == SD.KAM_OWNER_ID or (r.get("Stage") or "").strip() not in SD.ETAPAS_VENDIDO:
                    continue
                d = SD.dar_forma(r)
                if d["id"] not in vistos_c:
                    vistos_c.add(d["id"]); comercial.append(d)
    except Exception:
        comercial = []
    # implementaciones abiertas en México (módulo Implementaciones); si falla, se sirve sin ellas
    implementaciones = []
    try:
        qs = urllib.parse.urlencode({"criteria": SD.CRITERIO_IMPLEMENTACIONES,
                                     "fields": SD.CAMPOS_IMPLEMENTACIONES, "per_page": 200})
        status, cuerpo = pedir(f"{ZOHO_API}/crm/v8/Implementaciones/search?{qs}",
                               headers={"Authorization": f"Zoho-oauthtoken {token}"})
        if status == 200:
            implementaciones = [SD.forma_implementacion(r) for r in json.loads(cuerpo).get("data") or []]
    except Exception:
        implementaciones = []
    payload = {
        "generado": ahora_iso(),
        "fuente": "Zoho CRM · Deals (en vivo)",
        "propietario": SD.KAM_OWNER_NOMBRE,
        "territorio": SD.TERRITORIO_ESPERADO,
        "kams": SD.KAMS_VALIDOS,
        "total": len(deals),
        "deals": deals,
        "comercial": comercial,
        "implementaciones": implementaciones,
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


# ------------------------------------------------------------------ fuentes con caché y respaldo

FUENTES = {
    "cartera": {"leer": leer_cartera, "respaldo": RAIZ / "cartera.xlsx",
                "tipo": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    "deals": {"leer": leer_deals, "respaldo": RAIZ / "deals-mx.json",
              "tipo": "application/json; charset=utf-8"},
}


def meta_subida():
    try:
        return json.loads(SUBIDA_META.read_text(encoding="utf-8")) if SUBIDA.is_file() else None
    except (OSError, ValueError):
        return None


def validar_xlsx(datos):
    """Error en texto si no es un Cuentas Postventa sano; None si está bien."""
    if not datos.startswith(b"PK"):
        return "no es un .xlsx"
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            libro = z.read("xl/workbook.xml").decode("utf-8", "replace")
    except (zipfile.BadZipFile, KeyError) as e:
        return f".xlsx dañado o a medio guardar ({e})"
    if 'name="MARE MX"' not in libro:
        return "no tiene la hoja «MARE MX»: ¿es otra copia del archivo?"
    return None


def guardar_subida(datos, modificado):
    DATOS.mkdir(parents=True, exist_ok=True)
    tmp = SUBIDA.with_suffix(".tmp")
    tmp.write_bytes(datos)
    tmp.replace(SUBIDA)
    meta = {"sha256": hashlib.sha256(datos).hexdigest(), "bytes": len(datos),
            "recibido": ahora_iso(), "modificado_en_onedrive": modificado}
    SUBIDA_META.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    _cache.pop("cartera", None)
    return meta


def obtener(nombre):
    """Devuelve (bytes, fuente) con fuente 'en-vivo' | 'cache' | 'sincronizada' | 'respaldo'."""
    f, est = FUENTES[nombre], ESTADO[nombre]
    if nombre == "cartera" and not microsoft_configurado():
        m = meta_subida()
        if m:
            return SUBIDA.read_bytes(), "sincronizada"
    with _locks[nombre]:  # dos clics seguidos no disparan dos descargas
        c = _cache.get(nombre)
        if c and time.time() - c["t"] < CACHE_SEGUNDOS:
            return c["datos"], "cache"
        try:
            datos = f["leer"]()
            _cache[nombre] = {"t": time.time(), "datos": datos}
            est.update(ultima_ok=ahora_iso(), error=None, bytes=len(datos))
            return datos, "en-vivo"
        except FuenteError as e:
            est.update(error=str(e), ultimo_error=ahora_iso())
        except Exception as e:  # red caída, JSON raro, etc.
            traceback.print_exc()
            est.update(error=f"{type(e).__name__}: {e}", ultimo_error=ahora_iso())
        print(f"[{nombre}] usando respaldo del repo: {est['error']}", flush=True)
        if c:  # mejor la última lectura buena que el archivo del repo
            return c["datos"], "respaldo"
        return f["respaldo"].read_bytes(), "respaldo"


def microsoft_configurado():
    return all(ENV(k) for k in ("MS_TENANT_ID", "MS_CLIENT_ID", "MS_REFRESH_TOKEN"))


def estado():
    return {
        "cartera_sincronizada_desde_mac": meta_subida(),
        "servidor": ahora_iso(),
        "clave": bool(ENV("TABLERO_CLAVE")),
        "microsoft_configurado": microsoft_configurado(),
        "zoho_configurado": all(ENV(k) for k in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN")),
        "cache_segundos": CACHE_SEGUNDOS,
        "fuentes": ESTADO,
    }


# ------------------------------------------------------------------ servidor

class Manejador(BaseHTTPRequestHandler):
    server_version = "MonitorCartera/1.0"

    def log_message(self, fmt, *args):
        print("%s %s" % (self.address_string(), fmt % args), flush=True)

    def autorizado(self):
        clave = ENV("TABLERO_CLAVE")
        if not clave:
            return True
        cab = self.headers.get("Authorization", "")
        if cab.startswith("Basic "):
            try:
                _, _, dada = base64.b64decode(cab[6:]).decode("utf-8").partition(":")
                if hmac.compare_digest(dada.encode(), clave.encode()):
                    return True
            except Exception:
                pass
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Monitor de Cartera MX", charset="UTF-8"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Pide la contraseña a Fernanda Durán. El usuario puede ser cualquiera.".encode())
        return False

    def responder(self, cuerpo, tipo, extra=None, codigo=200):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(cuerpo)

    def do_HEAD(self):
        self.do_GET()

    # ---- subida desde la Mac (no usa TABLERO_CLAVE: tiene su propia clave)
    def clave_subida_ok(self):
        clave = ENV("CARTERA_SUBIDA_CLAVE")
        dada = self.headers.get("X-Clave-Subida", "")
        if clave and hmac.compare_digest(dada.encode(), clave.encode()):
            return True
        self.responder(json.dumps({"error": "clave de subida incorrecta o no configurada"}).encode(),
                       "application/json", codigo=403)
        return False

    def version_subida(self):
        if not self.clave_subida_ok():
            return
        self.responder(json.dumps(meta_subida() or {}).encode(), "application/json")

    def do_POST(self):
        ruta = urllib.parse.urlparse(self.path).path
        if ruta != "/api/cartera":
            return self.responder(b"No encontrado", "text/plain", codigo=404)
        if not self.clave_subida_ok():
            return
        largo = int(self.headers.get("Content-Length") or 0)
        if not 0 < largo <= TAM_MAX_SUBIDA:
            return self.responder(b'{"error":"tamano invalido"}', "application/json", codigo=413)
        datos = self.rfile.read(largo)
        error = validar_xlsx(datos)
        if error:
            return self.responder(json.dumps({"error": error}, ensure_ascii=False).encode(),
                                  "application/json; charset=utf-8", codigo=422)
        meta = guardar_subida(datos, self.headers.get("X-Modificado", ""))
        print(f"[cartera] recibida desde la Mac: {meta['bytes']} bytes, {meta['sha256'][:12]}", flush=True)
        self.responder(json.dumps(meta).encode(), "application/json")

    def do_GET(self):
        ruta = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
        if ruta == "/salud-servidor":  # para el health check de Replit, sin clave
            return self.responder(b"ok", "text/plain")
        if ruta == "/api/cartera":  # la Mac pregunta qué versión tiene el servidor (clave propia)
            return self.version_subida()
        if not self.autorizado():
            return
        if ruta in ("/cartera.xlsx", "/Cuentas_Postventa.xlsx"):
            return self.servir_fuente("cartera")
        if ruta == "/deals-mx.json":
            return self.servir_fuente("deals")
        if ruta == "/api/estado":
            return self.responder(json.dumps(estado(), ensure_ascii=False, indent=2).encode(),
                                  "application/json; charset=utf-8")
        return self.servir_archivo(ruta)

    def servir_fuente(self, nombre):
        datos, fuente = obtener(nombre)
        extra = {"X-Fuente": fuente}
        if fuente == "sincronizada":
            m = meta_subida() or {}
            extra["X-Fuente-Fecha"] = m.get("modificado_en_onedrive") or m.get("recibido", "")
        if ESTADO[nombre].get("error") and fuente == "respaldo":
            extra["X-Fuente-Error"] = urllib.parse.quote(ESTADO[nombre]["error"][:300])
        self.responder(datos, FUENTES[nombre]["tipo"], extra)

    def servir_archivo(self, ruta):
        if ruta in ("", "/"):
            ruta = "/index.html"
        partes = [p for p in ruta.split("/") if p]
        destino = RAIZ.joinpath(*partes).resolve() if partes else RAIZ / "index.html"
        if (any(p.startswith(".") for p in partes) or (partes and partes[0] == "scripts")
                or RAIZ not in destino.parents or destino.suffix.lower() not in EXT_PUBLICAS
                or not destino.is_file()):
            return self.responder(b"No encontrado", "text/plain; charset=utf-8", codigo=404)
        tipo = mimetypes.guess_type(destino.name)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo == "application/json":
            tipo += "; charset=utf-8"
        self.responder(destino.read_bytes(), tipo)


def main():
    puerto = int(ENV("PORT", "8000"))
    e = estado()
    print(f"Monitor de Cartera MX en el puerto {puerto}", flush=True)
    print(f"  contraseña: {'sí' if e['clave'] else 'NO (tablero abierto)'} · "
          f"OneDrive: {'directo' if e['microsoft_configurado'] else ('copia desde la Mac' if ENV('CARTERA_SUBIDA_CLAVE') else 'sin credenciales → respaldo')} · "
          f"Zoho: {'configurado' if e['zoho_configurado'] else 'sin credenciales → respaldo'}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", puerto), Manejador).serve_forever()


if __name__ == "__main__":
    main()
