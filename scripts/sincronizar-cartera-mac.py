#!/usr/bin/env python3
"""
Manda «Cuentas Postventa.xlsx» desde la carpeta de OneDrive sincronizada en
esta Mac al Monitor de Cartera en Replit, cada vez que cambia.

Es el puente mientras TI no registre la app de Entra ID (con esa app,
servidor.py baja el archivo directo de OneDrive y esto ya no hace falta).

    python3 scripts/sincronizar-cartera-mac.py configurar   # una vez: URL + clave, y lo deja corriendo
    python3 scripts/sincronizar-cartera-mac.py estado       # qué tiene Replit y qué hay en la Mac
    python3 scripts/sincronizar-cartera-mac.py sincronizar  # una pasada a mano (es lo que corre launchd)
    python3 scripts/sincronizar-cartera-mac.py desinstalar  # lo apaga

Corre cada 5 minutos con launchd. macOS no deja que un proceso en segundo
plano lea la carpeta de OneDrive, así que launchd abre una mini app
(~/Applications/Sincronizar Cartera.app) que sí puede pedir ese permiso — una
sola vez, con el aviso «… quiere acceder a archivos de OneDrive» → Permitir —
y es la que corre esta pasada. Así no hace falta darle acceso total al disco a
Python. En
cada pasada compara el hash del archivo con el que tiene el servidor y solo
sube si son distintos — así también repone la copia si Replit reinició la
instancia. Solo funciona con la Mac prendida y con la sesión abierta.

La URL y la clave de subida (= el Secret CARTERA_SUBIDA_CLAVE de Replit) se
guardan en ~/.config/monitor-cartera/replit.json con permisos 600, nunca en el repo.
Log: ~/Library/Logs/monitor-cartera-sync.log

Solo usa la librería estándar de Python 3.
"""

import datetime as dt
import getpass
import glob
import hashlib
import io
import json
import os
import plistlib
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ETIQUETA = "com.geovictoria.monitor-cartera-sync"
CONFIG = Path.home() / ".config" / "monitor-cartera" / "replit.json"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{ETIQUETA}.plist"
LOG = Path.home() / "Library" / "Logs" / "monitor-cartera-sync.log"
APP = Path.home() / "Applications" / "Sincronizar Cartera.app"
# El archivo real está en la carpeta PostVenta; en la raíz del OneDrive hay docenas de copias viejas.
PATRON = str(Path.home() / "Library" / "CloudStorage" / "OneDrive-*" / "PostVenta" / "Cuentas Postventa.xlsx")


def log(msg):
    linea = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(linea, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 512 * 1024:  # que no crezca sin fin
            LOG.write_text(LOG.read_text(encoding="utf-8")[-128 * 1024:], encoding="utf-8")
        with LOG.open("a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except OSError:
        pass


def archivo():
    hallados = glob.glob(PATRON)
    if not hallados:
        sys.exit(f"No encuentro {PATRON}. ¿OneDrive está abierto y la carpeta PostVenta sincronizada?")
    return Path(hallados[0])


def leer_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sys.exit("Falta configurar: python3 scripts/sincronizar-cartera-mac.py configurar")


def pedir(cfg, metodo, datos=None, extra=None):
    req = urllib.request.Request(cfg["url"].rstrip("/") + "/api/cartera", data=datos, method=metodo,
                                 headers={"X-Clave-Subida": cfg["clave"], **(extra or {})})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def validar(datos):
    if not datos.startswith(b"PK"):
        return "no es un .xlsx (¿OneDrive todavía lo está bajando?)"
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            if 'name="MARE MX"' not in z.read("xl/workbook.xml").decode("utf-8", "replace"):
                return "no tiene la hoja «MARE MX»"
    except (zipfile.BadZipFile, KeyError) as e:
        return f"está a medio guardar ({e})"
    return None


def sincronizar(forzar=False):
    cfg = leer_config()
    ruta = archivo()
    try:
        datos = ruta.read_bytes()  # si OneDrive lo tenía solo en la nube, esto lo baja
    except OSError as e:
        log(f"no pude leer el Excel: {e}")
        return 1
    error = validar(datos)
    if error:
        log(f"no subo: el archivo {error}; reintento en la próxima pasada")
        return 0
    sha = hashlib.sha256(datos).hexdigest()
    st, remoto = pedir(cfg, "GET")
    if st == 403:
        log("Replit rechazó la clave de subida: revisa CARTERA_SUBIDA_CLAVE y vuelve a correr configurar")
        return 1
    if st != 200:
        log(f"Replit no respondió bien (HTTP {st}); reintento en la próxima pasada")
        return 1
    if remoto.get("sha256") == sha and not forzar:
        return 0  # sin cambios: no ensucia el log
    modificado = dt.datetime.fromtimestamp(ruta.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    st, r = pedir(cfg, "POST", datos, {"Content-Type": "application/octet-stream", "X-Modificado": modificado})
    if st == 200:
        log(f"subido: {len(datos) // 1024} KB, guardado en OneDrive {modificado}")
        return 0
    log(f"Replit rechazó el archivo (HTTP {st}): {r.get('error', '')}")
    return 1


def estado():
    cfg = leer_config()
    ruta = archivo()
    datos = ruta.read_bytes()
    print(f"Mac:     {ruta}\n         {len(datos) // 1024} KB, modificado "
          f"{dt.datetime.fromtimestamp(ruta.stat().st_mtime):%d-%m %H:%M}, sha {hashlib.sha256(datos).hexdigest()[:12]}")
    st, remoto = pedir(cfg, "GET")
    if st != 200:
        print(f"Replit:  HTTP {st} {remoto.get('error', '')}")
    elif not remoto:
        print("Replit:  todavía no tiene ninguna copia")
    else:
        print(f"Replit:  {remoto.get('bytes', 0) // 1024} KB, recibido {remoto.get('recibido')}, sha {remoto.get('sha256', '')[:12]}")
    corriendo = subprocess.run(["launchctl", "list", ETIQUETA], capture_output=True).returncode == 0
    print(f"Proceso: {'corriendo cada 5 min' if corriendo else 'apagado'} · log en {LOG}")


def configurar():
    url = input("URL del tablero en Replit (ej. https://monitor-cartera-mx.replit.app): ").strip().rstrip("/")
    if not url.startswith("https://") and not url.startswith("http://localhost"):
        sys.exit("La URL tiene que empezar con https://")
    clave = getpass.getpass("Clave de subida (el Secret CARTERA_SUBIDA_CLAVE; no se ve al escribir): ").strip()
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps({"url": url, "clave": clave}), encoding="utf-8")
    os.chmod(CONFIG, 0o600)
    print("✓ configuración guardada")

    st, r = pedir({"url": url, "clave": clave}, "GET")
    if st != 200:
        sys.exit(f"Replit respondió HTTP {st} {r.get('error', '')}. Revisa la URL y que el Secret "
                 "CARTERA_SUBIDA_CLAVE esté cargado y el deploy actualizado.")
    print("✓ Replit acepta la clave")

    if sincronizar(forzar=True) != 0:
        sys.exit("La primera subida falló; mira el mensaje de arriba.")

    crear_app()
    plist = {
        "Label": ETIQUETA,
        "ProgramArguments": ["/usr/bin/open", "-g", "-j", str(APP)],
        "StartInterval": 300,
        "RunAtLoad": True,
    }
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
    with PLIST.open("wb") as f:
        plistlib.dump(plist, f)
    subprocess.run(["launchctl", "load", str(PLIST)], check=True)
    print(f"✓ queda corriendo cada 5 minutos ({PLIST.name})")
    print("  Si aparece «“Sincronizar Cartera” quiere acceder a archivos de OneDrive», pulsa Permitir.")
    print("  En 1 minuto revisa: python3 scripts/sincronizar-cartera-mac.py estado")


def crear_app():
    """Mini app de AppleScript que corre la pasada; launchd la abre para que el permiso sea suyo."""
    comando = f"{sys.executable} {Path(__file__).resolve()} sincronizar"
    script = f'do shell script {json.dumps(comando)}'
    subprocess.run(["rm", "-rf", str(APP)], check=True)
    APP.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["osacompile", "-o", str(APP), "-e", script], check=True)
    info = APP / "Contents" / "Info.plist"
    with info.open("rb") as f:
        datos = plistlib.load(f)
    datos["LSUIElement"] = True  # sin ícono en el Dock cada 5 minutos
    datos["CFBundleIdentifier"] = "com.geovictoria.sincronizar-cartera"
    with info.open("wb") as f:
        plistlib.dump(datos, f)
    subprocess.run(["codesign", "--force", "--deep", "-s", "-", str(APP)], check=True, capture_output=True)
    print(f"✓ app creada en {APP}")


def desinstalar():
    subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
    PLIST.unlink(missing_ok=True)
    subprocess.run(["rm", "-rf", str(APP)])
    print("✓ apagado. La configuración sigue en", CONFIG)


if __name__ == "__main__":
    accion = sys.argv[1] if len(sys.argv) > 1 else ""
    acciones = {"configurar": configurar, "estado": estado, "desinstalar": desinstalar,
                "sincronizar": lambda: sys.exit(sincronizar(forzar="--forzar" in sys.argv))}
    if accion not in acciones:
        sys.exit(__doc__)
    acciones[accion]()
