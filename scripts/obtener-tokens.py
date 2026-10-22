#!/usr/bin/env python3
"""
Saca los refresh tokens que necesita servidor.py en Replit, y los prueba.

    python3 scripts/obtener-tokens.py microsoft
    python3 scripts/obtener-tokens.py zoho

Se corre UNA vez en tu Mac (y de nuevo si un token vence o se revoca). Al final
imprime el valor para pegar en los Secrets de Replit. No guarda nada en disco
ni en el repo — el repo es público.

Microsoft — antes, en portal.azure.com → Entra ID → App registrations
(lo hace TI si tu cuenta no puede):
  1. New registration · "Monitor Cartera MX" · Single tenant · sin Redirect URI.
  2. Authentication → "Allow public client flows" = Yes.
  3. API permissions → Microsoft Graph → Delegated → Files.Read (+ offline_access).
  Copia "Application (client) ID" y "Directory (tenant) ID".

Zoho — antes, en https://api-console.zoho.com:
  1. Add Client → Self Client → Create. Copia Client ID y Client Secret.
  2. Pestaña "Generate Code" · Scope: ZohoCRM.modules.deals.READ
     · Time duration: 10 minutes · Create. Copia el código (dura 10 min).

Solo usa la librería estándar de Python 3.
"""

import getpass
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DRIVE_ID = "b!sAG5r_bfbEGvk01PB7t4cQzL2hbo70NNv2KSjMR1GulyjRiY0B71TJsImZRJSNRV"
ITEM_ID = "01FBJR3VU6WJGDP3GGFZHL6WFG5C5WDSPN"
ZOHO_CRITERIA = ("((Owner:equals:3525045000270215054)and((KAM:equals:Dafne de la Rosa)"
                 "or(KAM:equals:Raúl Campos)or(KAM:equals:Karla Patiño)))")


def pedir(url, data=None, headers=None):
    if isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def preguntar(texto, secreto=False):
    v = (getpass.getpass if secreto else input)(f"{texto}: ").strip()
    if not v:
        sys.exit(f"Falta {texto}.")
    return v


def mostrar(secrets):
    print("\nListo. Pega esto en Replit → Tools → Secrets (uno por línea, nombre = valor).")
    print("No lo pegues en chats, correos ni en el repo.\n")
    for k, v in secrets.items():
        print(f"  {k} = {v}")
    print()


def microsoft():
    tenant = preguntar("Directory (tenant) ID")
    cliente = preguntar("Application (client) ID")
    scope = "offline_access Files.Read"
    st, j = pedir(f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode",
                  {"client_id": cliente, "scope": scope})
    if st != 200:
        sys.exit(f"Microsoft no inició el login: {j.get('error')} — {j.get('error_description', '')[:300]}\n"
                 "Revisa que la app tenga 'Allow public client flows' = Yes.")
    print(f"\n1. Abre {j['verification_uri']}\n2. Escribe el código {j['user_code']}\n"
          "3. Entra con tu cuenta de GeoVictoria y acepta.\n\nEsperando…")
    fin = time.time() + int(j.get("expires_in", 900))
    while time.time() < fin:
        time.sleep(int(j.get("interval", 5)))
        st, t = pedir(f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                      {"client_id": cliente, "device_code": j["device_code"],
                       "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        if st == 200:
            break
        if t.get("error") not in ("authorization_pending", "slow_down"):
            sys.exit(f"Login rechazado: {t.get('error')} — {t.get('error_description', '')[:300]}\n"
                     "Si dice que hace falta consentimiento de un administrador, eso lo aprueba TI.")
    else:
        sys.exit("Se acabó el tiempo para aceptar. Vuelve a correr el script.")

    st, meta = pedir(f"https://graph.microsoft.com/v1.0/drives/{DRIVE_ID}/items/{ITEM_ID}",
                     headers={"Authorization": f"Bearer {t['access_token']}"})
    if st != 200:
        sys.exit(f"El token sirve pero no pudo leer Cuentas Postventa.xlsx (HTTP {st}): {meta.get('error')}")
    print(f"✓ Lee «{meta.get('name')}» ({meta.get('size', 0) // 1024} KB, "
          f"modificado {meta.get('lastModifiedDateTime')} por "
          f"{(meta.get('lastModifiedBy') or {}).get('user', {}).get('displayName', '?')})")
    mostrar({"MS_TENANT_ID": tenant, "MS_CLIENT_ID": cliente, "MS_REFRESH_TOKEN": t["refresh_token"]})


def zoho():
    cliente = preguntar("Client ID del Self Client")
    secreto = preguntar("Client Secret (no se ve al escribir)", secreto=True)
    codigo = preguntar("Código generado en 'Generate Code' (dura 10 min)", secreto=True)
    st, t = pedir("https://accounts.zoho.com/oauth/v2/token",
                  {"grant_type": "authorization_code", "client_id": cliente,
                   "client_secret": secreto, "code": codigo})
    if st != 200 or "refresh_token" not in t:
        sys.exit(f"Zoho no entregó refresh token: {t.get('error', st)}. "
                 "Si dice invalid_code, el código venció o ya se usó: genera otro.")
    qs = urllib.parse.urlencode({"criteria": ZOHO_CRITERIA, "fields": "id", "per_page": 200})
    st, r = pedir(f"https://www.zohoapis.com/crm/v8/Deals/search?{qs}",
                  headers={"Authorization": f"Zoho-oauthtoken {t['access_token']}"})
    if st not in (200, 204):
        sys.exit(f"El token sirve pero la búsqueda de deals falló (HTTP {st}): {r.get('code')} {r.get('message')}")
    n = len(r.get("data") or [])
    mas = " (y hay más páginas)" if (r.get("info") or {}).get("more_records") else ""
    print(f"✓ Zoho devuelve {n} deals de KAM México en la primera página{mas}")
    mostrar({"ZOHO_CLIENT_ID": cliente, "ZOHO_CLIENT_SECRET": secreto, "ZOHO_REFRESH_TOKEN": t["refresh_token"]})


if __name__ == "__main__":
    que = sys.argv[1] if len(sys.argv) > 1 else ""
    if que == "microsoft":
        microsoft()
    elif que == "zoho":
        zoho()
    else:
        sys.exit(__doc__)
