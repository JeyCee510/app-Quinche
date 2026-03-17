import streamlit as st
import pandas as pd
import plotly.express as px
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
import os
import json
import time
import sqlite3
import shutil
import subprocess
from groq import Groq

# ==========================================
# CONFIGURACIÓN DE CORREO (CREDENCIALES SEGURAS)
# ==========================================
REMITENTE = "jclira@gmail.com"  
PASSWORD_APP = st.secrets["EMAIL_PASSWORD"].replace(" ", "") 

# ==========================================
# GESTIÓN DE BASES DE DATOS Y ARCHIVOS (SQLITE)
# ==========================================
DB_NAME = "quinche_data.db"
ARCHIVO_CONFIG = "quinche_config.json"
CARPETA_ADJUNTOS = "comprobantes"

if not os.path.exists(CARPETA_ADJUNTOS):
    os.makedirs(CARPETA_ADJUNTOS)

ESTRUCTURA_TABLAS = {
    "master": ["Fecha", "Tipo", "Categoría", "Monto", "Concepto", "Detalle", "Adjuntos"],
    "inversiones": ["Fecha Inicio", "Entidad", "Monto", "Tasa Anual (%)", "Plazo (días)", "Fecha Vencimiento", "Interés Generado", "Estado"],
    "activos": ["Fecha", "Deudor", "Concepto", "Monto", "Fecha Esperada", "Estado"],
    "prov_hist": ["Fecha", "Rubro", "Acumulado"]
}

def init_db():
    conn = sqlite3.connect(DB_NAME)
    archivos_legacy = {
        "master": "quinche_master.csv",
        "inversiones": "quinche_inversiones.csv",
        "activos": "quinche_activos.csv",
        "prov_hist": "quinche_prov_hist.csv"
    }
    for tabla, columnas in ESTRUCTURA_TABLAS.items():
        query = conn.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{tabla}'").fetchone()
        if not query:
            archivo_antiguo = archivos_legacy[tabla]
            if os.path.exists(archivo_antiguo):
                df_temp = pd.read_csv(archivo_antiguo)
                df_temp.to_sql(tabla, conn, index=False)
            else:
                df_temp = pd.DataFrame(columns=columnas)
                df_temp.to_sql(tabla, conn, index=False)
    conn.close()

def cargar_tabla(nombre_tabla):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query(f"SELECT * FROM {nombre_tabla}", conn)
    conn.close()
    
    for col in ['Fecha', 'Fecha Inicio', 'Fecha Esperada', 'Fecha Vencimiento']:
        if col in df.columns: df[col] = pd.to_datetime(df[col], errors='coerce')
    for col in ['Monto', 'Acumulado', 'Interés Generado']:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    return df

def guardar_tabla(nombre_tabla, df):
    conn = sqlite3.connect(DB_NAME)
    df_save = df.copy()
    for col in df_save.select_dtypes(include=['datetime64[ns]', 'datetime64[ns, UTC]']).columns:
        df_save[col] = df_save[col].dt.strftime('%Y-%m-%d')
    df_save.to_sql(nombre_tabla, conn, if_exists='replace', index=False)
    conn.close()

def agregar_filas_a_tabla(nombre_tabla, lista_diccionarios):
    if not lista_diccionarios: return
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    columnas = list(lista_diccionarios[0].keys())
    columnas_str = ", ".join([f'"{col}"' for col in columnas]) 
    placeholders = ", ".join(["?"] * len(columnas))
    query = f'INSERT INTO "{nombre_tabla}" ({columnas_str}) VALUES ({placeholders})'
    
    valores_a_insertar = []
    for fila in lista_diccionarios:
        valores_fila = []
        for col in columnas:
            val = fila.get(col, None)
            if isinstance(val, (datetime, pd.Timestamp)):
                val = val.strftime('%Y-%m-%d')
            valores_fila.append(val)
        valores_a_insertar.append(tuple(valores_fila))
        
    try:
        cursor.executemany(query, valores_a_insertar)
        conn.commit()
    except Exception as e:
        print(f"Error al insertar datos: {e}")
        conn.rollback()
    finally:
        conn.close()

init_db()
df = cargar_tabla("master")
df_inv = cargar_tabla("inversiones")
df_act = cargar_tabla("activos")
df_prov_hist = cargar_tabla("prov_hist")

# ==========================================
# GESTIÓN DE CORREOS
# ==========================================
def enviar_alerta(fecha, tipo, categoria, monto, concepto, detalle, rutas_adjuntos, comision, destinatarios):
    try:
        if not destinatarios: return False
        msg = MIMEMultipart()
        msg['From'] = REMITENTE
        msg['To'] = ", ".join(destinatarios)
        msg['Subject'] = f"🔔 Nuevo {tipo}: ${monto:.2f} - {categoria.title()} El Quinche"

        cuerpo = f"""
        Se ha registrado un movimiento en tu sistema financiero:
        
        Fecha: {fecha.strftime('%d/%m/%Y') if isinstance(fecha, datetime) else pd.to_datetime(fecha).strftime('%d/%m/%Y')}
        Tipo: {tipo}
        Categoría: {categoria}
        Monto Principal: ${monto:.2f}
        Concepto: {concepto}
        Detalle: {detalle}
        """
        if comision > 0: cuerpo += f"Comisión Bancaria: ${comision:.2f} (Registrada como gasto adicional)\n"

        msg.attach(MIMEText(cuerpo, 'plain'))

        if rutas_adjuntos:
            for ruta in rutas_adjuntos:
                if os.path.exists(ruta):
                    with open(ruta, "rb") as f:
                        part = MIMEBase('application', 'octet-stream')
                        part.set_payload(f.read())
                        encoders.encode_base64(part)
                        nombre_archivo = os.path.basename(ruta)
                        part.add_header('Content-Disposition', f'attachment; filename="{nombre_archivo}"')
                        msg.attach(part)

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(REMITENTE, PASSWORD_APP)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Error al enviar correo: {e}")
        return False

def enviar_reporte_dashboard(destinatarios, saldo, inv, cxc, prov, ingresos, gastos, start_date, end_date, archivos_adjuntos, df_movimientos, datos_prov, mensaje_personalizado, df_inversiones, df_cuentas_cobrar):
    try:
        if not destinatarios: return False
        msg = MIMEMultipart('alternative')
        msg['From'] = REMITENTE
        msg['To'] = ", ".join(destinatarios)
        msg['Subject'] = f"📊 Reporte Dashboard: El Quinche (Periodo: {start_date.strftime('%d/%m/%Y')} al {end_date.strftime('%d/%m/%Y')})"
        
        mensaje_html = ""
        if mensaje_personalizado.strip():
            mensaje_html = f"""<div style="background-color: #f1f8ff; padding: 15px; border-left: 4px solid #709b8b; margin-bottom: 20px; font-size: 14px;">{mensaje_personalizado.replace(chr(10), '<br>')}</div>"""

        tabla_movimientos_html = ""
        if not df_movimientos.empty:
            tabla_movimientos_html = """
            <h3 style="color: #4b6b5d; margin-top: 30px;">📄 Detalle de Movimientos en el Periodo:</h3>
            <table style="width: 100%; border-collapse: collapse; font-size: 13px; text-align: left;">
                <tr style="background-color: #4b6b5d; color: white;">
                    <th style="padding: 8px; border: 1px solid #ddd;">Fecha</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">Tipo</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">Categoría</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">Concepto</th>
                    <th style="padding: 8px; border: 1px solid #ddd; text-align: right;">Monto</th>
                </tr>
            """
            for _, row in df_movimientos.iterrows():
                fecha_str = pd.to_datetime(row['Fecha']).strftime('%d/%m/%Y')
                color_texto = "#709b8b" if row['Tipo'] == "Ingreso" else "#c9806b"
                tabla_movimientos_html += f"""
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">{fecha_str}</td>
                    <td style="padding: 8px; border: 1px solid #ddd; color: {color_texto}; font-weight: bold;">{row['Tipo']}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{row['Categoría']}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{row['Concepto']}</td>
                    <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">${row['Monto']:.2f}</td>
                </tr>
                """
            tabla_movimientos_html += "</table>"
        else:
            tabla_movimientos_html = "<p><i>No hay movimientos registrados.</i></p>"

        tabla_inv_html = ""
        if df_inversiones is not None and not df_inversiones.empty:
            activas = df_inversiones[df_inversiones['Estado'] == 'Activa']
            if not activas.empty:
                tabla_inv_html = """<h3 style="color: #4b6b5d; margin-top: 30px;">📈 Detalle de Inversiones Activas:</h3><table style="width: 100%; border-collapse: collapse; font-size: 13px; text-align: left;"><tr style="background-color: #4b6b5d; color: white;"><th style="padding: 8px; border: 1px solid #ddd;">Entidad</th><th style="padding: 8px; border: 1px solid #ddd;">Fecha Venc.</th><th style="padding: 8px; border: 1px solid #ddd; text-align: right;">Monto Invertido</th><th style="padding: 8px; border: 1px solid #ddd; text-align: right;">Interés Proyectado</th></tr>"""
                for _, row in activas.iterrows():
                    f_venc = str(row['Fecha Vencimiento'])[:10]
                    tabla_inv_html += f"""<tr><td style="padding: 8px; border: 1px solid #ddd;">{row['Entidad']}</td><td style="padding: 8px; border: 1px solid #ddd;">{f_venc}</td><td style="padding: 8px; border: 1px solid #ddd; text-align: right;">${row['Monto']:,.2f}</td><td style="padding: 8px; border: 1px solid #ddd; text-align: right; color: #709b8b;">+${row['Interés Generado']:,.2f}</td></tr>"""
                tabla_inv_html += "</table>"

        tabla_cxc_html = ""
        if df_cuentas_cobrar is not None and not df_cuentas_cobrar.empty:
            pendientes = df_cuentas_cobrar[df_cuentas_cobrar['Estado'] == 'Pendiente']
            if not pendientes.empty:
                tabla_cxc_html = """<h3 style="color: #c9806b; margin-top: 30px;">🤝 Detalle de Cuentas por Cobrar:</h3><table style="width: 100%; border-collapse: collapse; font-size: 13px; text-align: left;"><tr style="background-color: #4b6b5d; color: white;"><th style="padding: 8px; border: 1px solid #ddd;">Deudor</th><th style="padding: 8px; border: 1px solid #ddd;">Concepto</th><th style="padding: 8px; border: 1px solid #ddd;">Fecha Esperada</th><th style="padding: 8px; border: 1px solid #ddd; text-align: right;">Monto</th></tr>"""
                for _, row in pendientes.iterrows():
                    f_esp = str(row['Fecha Esperada'])[:10]
                    tabla_cxc_html += f"""<tr><td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">{row['Deudor']}</td><td style="padding: 8px; border: 1px solid #ddd;">{row['Concepto']}</td><td style="padding: 8px; border: 1px solid #ddd;">{f_esp}</td><td style="padding: 8px; border: 1px solid #ddd; text-align: right;">${row['Monto']:,.2f}</td></tr>"""
                tabla_cxc_html += "</table>"

        tabla_prov_html = """<h3 style="color: #c9806b; margin-top: 30px;">💰 Detalle de Fondo de Provisiones:</h3><table style="width: 100%; max-width: 500px; border-collapse: collapse; font-size: 13px; text-align: left;"><tr style="background-color: #4b6b5d; color: white;"><th style="padding: 8px; border: 1px solid #ddd;">Rubro</th><th style="padding: 8px; border: 1px solid #ddd; text-align: right;">Acumulado Actual</th></tr>"""
        for prov_item in datos_prov:
            tabla_prov_html += f"""<tr><td style="padding: 8px; border: 1px solid #ddd;">{prov_item['Rubro']}</td><td style="padding: 8px; border: 1px solid #ddd; text-align: right;">${prov_item['Acumulado']:,.2f}</td></tr>"""
        tabla_prov_html += f"""<tr style="background-color: #f1f4f2; font-weight: bold;"><td style="padding: 8px; border: 1px solid #ddd;">TOTAL INMOVILIZADO</td><td style="padding: 8px; border: 1px solid #ddd; text-align: right; color: #c9806b;">${prov:,.2f}</td></tr></table>"""

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
            {mensaje_html}
            <h2 style="color: #709b8b;">📊 Resumen Financiero - El Quinche</h2>
            <table style="width: 100%; max-width: 500px; border-collapse: collapse; margin-bottom: 20px;">
                <tr style="background-color: #f1f4f2;"><td style="padding: 10px; border: 1px solid #ddd;"><b>SALDO BANCARIO ACTUAL</b></td><td style="padding: 10px; border: 1px solid #ddd; text-align: right;"><b>${saldo:,.2f}</b></td></tr>
                <tr><td style="padding: 10px; border: 1px solid #ddd;">Inversiones Activas</td><td style="padding: 10px; border: 1px solid #ddd; text-align: right;">${inv:,.2f}</td></tr>
                <tr style="background-color: #f1f4f2;"><td style="padding: 10px; border: 1px solid #ddd;">Activos (Préstamos)</td><td style="padding: 10px; border: 1px solid #ddd; text-align: right;">${cxc:,.2f}</td></tr>
                <tr><td style="padding: 10px; border: 1px solid #ddd;">Fondo de Provisiones</td><td style="padding: 10px; border: 1px solid #ddd; text-align: right; color: #c9806b;">${prov:,.2f}</td></tr>
                <tr style="background-color: #e2e8e4;"><td style="padding: 10px; border: 1px solid #ddd;"><b>Patrimonio Líquido Total</b></td><td style="padding: 10px; border: 1px solid #ddd; text-align: right;"><b>${(saldo + inv + cxc):,.2f}</b></td></tr>
            </table>
            
            <h3 style="color: #4b6b5d;">📅 Resumen del Periodo ({start_date.strftime('%d/%m/%Y')} al {end_date.strftime('%d/%m/%Y')}):</h3>
            <ul style="list-style-type: none; padding: 0;">
                <li style="padding: 5px 0; border-bottom: 1px solid #eee;"><span style="color: #709b8b;">🟢 <b>Total Ingresos:</b></span> ${ingresos:,.2f}</li>
                <li style="padding: 5px 0;"><span style="color: #c9806b;">🔴 <b>Total Gastos:</b></span> ${gastos:,.2f}</li>
                <li style="padding: 5px 0; font-weight: bold; background-color: #f1f4f2;">Flujo Neto: ${(ingresos - gastos):,.2f}</li>
            </ul>
            {tabla_inv_html} {tabla_cxc_html} {tabla_movimientos_html} {tabla_prov_html}
        </body>
        </html>
        """
        msg.attach(MIMEText(html, 'html'))

        if archivos_adjuntos:
            for archivo in archivos_adjuntos:
                archivo.seek(0)
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(archivo.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename="{archivo.name}"')
                msg.attach(part)

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(REMITENTE, PASSWORD_APP)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Error al enviar reporte: {e}")
        return False

# ==========================================
# CONSTANTES Y CONFIGURACIÓN BASE
# ==========================================
CATEGORIAS_EXACTAS = [
    "sueldo (incluye FR)", "intereses recibidos", "inversión", "capital invertido", "alquiler", 
    "venta de aguacates", "servicios básicos", "infraestructura", 
    "mantenimiento de propiedad y equipos", "jardinería y exteriores", 
    "IESS", "Préstamo IESS", "gasolina aceite", "asignación Laura", "comisión banco", 
    "Prediales - Impuestos", "varios"
]

CORREOS_PREDEFINIDOS = ["jclira@gmail.com", "piriliri@gmail.com", "martingourmet@gmail.com", "sofilira@gmail.com", "camilalirac@gmail.com"]

def cargar_config():
    default_config = {
        "saldo_inicial": 0.0,
        "destinatarios": ["jclira@gmail.com"],
        "ultima_aplicacion_prov": "Nunca",
        "provisiones": {
            "Garantía": {"acumulado": 3055.51, "mensual": 53.17, "nota": "Fin contrato 30 abr 2027"},
            "13vo": {"acumulado": 112.50, "mensual": 37.50, "nota": "Se paga 15 diciembre"},
            "14vo": {"acumulado": 262.50, "mensual": 37.50, "nota": "Se paga 15 agosto"},
            "Prediales": {"acumulado": 230.00, "mensual": 115.00, "nota": "Se paga primeros días enero"},
            "Agua Pisque": {"acumulado": 13.33, "mensual": 13.33, "nota": "Se paga primeros días febrero"},
            "Reserva Varios": {"acumulado": 898.95, "mensual": 120.00, "nota": "Uso discrecional"}
        }
    }
    if os.path.exists(ARCHIVO_CONFIG):
        with open(ARCHIVO_CONFIG, 'r') as f:
            data = json.load(f)
            if "provisiones" not in data: data["provisiones"] = default_config["provisiones"]
            if "destinatarios" not in data: data["destinatarios"] = default_config["destinatarios"]
            if "ultima_aplicacion_prov" not in data: data["ultima_aplicacion_prov"] = default_config["ultima_aplicacion_prov"]
            return data
    return default_config

def guardar_config(config_data):
    with open(ARCHIVO_CONFIG, 'w') as f:
        json.dump(config_data, f)

config = cargar_config()
datos_prov_global = []
total_inmovilizado_global = 0
for clave, data in config["provisiones"].items():
    acumulado_real = float(data["acumulado"])
    total_inmovilizado_global += acumulado_real
    datos_prov_global.append({"Rubro": clave, "Acumulado": acumulado_real})

# ==========================================
# INTERFAZ DE USUARIO & ESTILOS SEGUROS
# ==========================================
st.set_page_config(page_title="Dashboard Quinche", layout="wide")

st.markdown("""
<style>
    [data-testid="stMetric"] {
        padding: 15px 20px;
        border-radius: 12px;
        border: 1px solid rgba(128, 128, 128, 0.2);
    }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { border-radius: 8px 8px 0 0; }
    div.stButton > button:first-child { border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

st.title("📊 Panel Financiero - El Quinche")

if 'form_data' not in st.session_state: st.session_state.form_data = {'tipo': 'Gasto', 'cat': CATEGORIAS_EXACTAS[0], 'concepto': '', 'es_prov': False, 'prov_key': ''}
if 'reg_tipo' not in st.session_state: st.session_state.reg_tipo = 'Gasto'
if 'reg_cat' not in st.session_state: st.session_state.reg_cat = CATEGORIAS_EXACTAS[0]
if 'reg_concepto' not in st.session_state: st.session_state.reg_concepto = ''
if 'filtro_categorias' not in st.session_state: st.session_state.filtro_categorias = CATEGORIAS_EXACTAS.copy()

def select_all_cats(): st.session_state.filtro_categorias = CATEGORIAS_EXACTAS.copy()
def clear_all_cats(): st.session_state.filtro_categorias = []

def set_quick_action(tipo, cat, concepto, es_prov=False, prov_key=''):
    st.session_state.form_data = {'tipo': tipo, 'cat': cat, 'concepto': concepto, 'es_prov': es_prov, 'prov_key': prov_key}
    st.session_state.reg_tipo = tipo
    st.session_state.reg_cat = cat
    st.session_state.reg_concepto = concepto

# --- FILTROS GLOBALES ---
st.sidebar.markdown("### 📅 Filtros de Visualización")
opcion_fecha = st.sidebar.radio("Periodo de análisis:", ["Este Mes", "Este Año", "Personalizado", "Todo el Historial"])

hoy = datetime.now().date()
if opcion_fecha == "Este Mes":
    start_date, end_date = pd.to_datetime(hoy.replace(day=1)), pd.to_datetime(hoy)
elif opcion_fecha == "Este Año":
    start_date, end_date = pd.to_datetime(hoy.replace(month=1, day=1)), pd.to_datetime(hoy)
elif opcion_fecha == "Personalizado":
    rango = st.sidebar.date_input("Selecciona el rango:", [hoy - timedelta(days=30), hoy])
    start_date, end_date = pd.to_datetime(rango[0]), pd.to_datetime(rango[1] if len(rango)==2 else hoy)
else:
    start_date = df['Fecha'].min() if not df.empty else pd.to_datetime(hoy)
    end_date = df['Fecha'].max() if not df.empty else pd.to_datetime(hoy)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🏷️ Filtrar por Categoría")
col_btn1, col_btn2 = st.sidebar.columns(2)
col_btn1.button("✅ Todas", on_click=select_all_cats)
col_btn2.button("❌ Ninguna", on_click=clear_all_cats)

categorias_seleccionadas = st.sidebar.multiselect(
    "Selecciona qué categorías ver (aplica al Dashboard y Edición):", 
    options=CATEGORIAS_EXACTAS, key='filtro_categorias'
)

st.sidebar.markdown("---")

# ==========================================
# 🌐 BOTÓN DE SINCRONIZACIÓN AUTOMÁTICA
# ==========================================
st.sidebar.markdown("### 🚀 Despliegue a la Nube")
RUTA_WEB = "../APP_Quinche_web" 

if st.sidebar.button("🌐 Sincronizar y Subir a GitHub", type="primary", width="stretch"):
    with st.spinner("Sincronizando con la nube..."):
        try:
            archivos_a_copiar = ["quinche_data.db", "quinche_config.json", "app.py"]
            for archivo in archivos_a_copiar:
                origen = os.path.join(".", archivo)
                destino = os.path.join(RUTA_WEB, archivo)
                if os.path.exists(origen):
                    shutil.copy2(origen, destino)
            
            subprocess.run(["git", "add", "."], cwd=RUTA_WEB, check=True)
            
            fecha_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            res_commit = subprocess.run(
                ["git", "commit", "-m", f"Auto-sync de base de datos: {fecha_str}"], 
                cwd=RUTA_WEB, capture_output=True, text=True
            )
            
            if "nothing to commit" in res_commit.stdout or "nada para hacer commit" in res_commit.stdout:
                st.sidebar.info("Archivos copiados, pero no había cambios nuevos para subir a GitHub.")
            else:
                subprocess.run(["git", "push"], cwd=RUTA_WEB, check=True)
                st.sidebar.success("¡Éxito! Base de datos subida a GitHub. La web se actualizará en unos segundos.")
                
        except Exception as e:
            st.sidebar.error(f"Error durante la sincronización: {e}")
            st.sidebar.info("Asegúrate de que la ruta RUTA_WEB sea correcta y que git esté configurado.")
            
st.sidebar.markdown("---")

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
    "📊 Dashboard", "➕ Registrar", "📝 Editar Data", "💰 Provisiones", 
    "📈 Inversiones", "🤝 Cuentas x Cobrar", "🧑‍🔧 Nómina Julio", "📧 Correos", "🤖 Asistente IA"
])

# --- TAB 1: DASHBOARD ---
with tab1:
    if not df.empty and len(df) > 0:
        df_filtered = df[(df['Fecha'] >= start_date) & (df['Fecha'] <= end_date)]
        df_filtered = df_filtered[df_filtered['Categoría'].isin(categorias_seleccionadas)]
        
        total_ingresos_historico = df[df['Tipo'] == 'Ingreso']['Monto'].sum()
        total_gastos_historico = df[df['Tipo'] == 'Gasto']['Monto'].sum()
        saldo_real_actual = config["saldo_inicial"] + total_ingresos_historico - total_gastos_historico
        
        ingresos_periodo = df_filtered[df_filtered['Tipo'] == 'Ingreso']['Monto'].sum()
        gastos_periodo = df_filtered[df_filtered['Tipo'] == 'Gasto']['Monto'].sum()
        
        total_inversiones = df_inv[df_inv['Estado'] == 'Activa']['Monto'].sum() if not df_inv.empty else 0.0
        total_cxc = df_act[df_act['Estado'] == 'Pendiente']['Monto'].sum() if not df_act.empty else 0.0

        col_head1, col_head2 = st.columns([2, 2])
        with col_head1:
            st.markdown("### Resumen de Liquidez y Activos Histórico")
        with col_head2:
            with st.expander("📤 Preparar y Enviar Resumen al Correo"):
                mensaje_personalizado = st.text_area("Añadir mensaje al correo (Opcional):", "")
                archivos_resumen = st.file_uploader("Adjuntar Estado de Cuenta / Documentos (Opcional)", accept_multiple_files=True, key="resumen_uploader")
                if st.button("Enviar Reporte Ahora"):
                    exito = enviar_reporte_dashboard(
                        config["destinatarios"], saldo_real_actual, total_inversiones, total_cxc, total_inmovilizado_global,
                        ingresos_periodo, gastos_periodo, start_date, end_date, archivos_resumen,
                        df_filtered.sort_values(by="Fecha", ascending=False), datos_prov_global, mensaje_personalizado,
                        df_inv, df_act
                    )
                    if exito: st.success("¡Reporte y adjuntos enviados exitosamente!")
                    else: st.error("Error al enviar el reporte.")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("SALDO BANCARIO ACTUAL", f"${saldo_real_actual:,.2f}")
        col2.metric("Inversiones Activas", f"${total_inversiones:,.2f}")
        col3.metric("Activos (Préstamos)", f"${total_cxc:,.2f}")
        col4.metric("Patrimonio Líquido Total", f"${saldo_real_actual + total_inversiones + total_cxc:,.2f}")
        
        st.markdown("---")
        
        col_resumen, col_radar = st.columns([2, 1])
        with col_resumen:
            st.markdown(f"### 🗓️ Resumen del Periodo ({start_date.strftime('%d/%m/%Y')} al {end_date.strftime('%d/%m/%Y')})")
            col_p1, col_p2, col_p3 = st.columns(3)
            col_p1.metric("Ingresos (Filtrados)", f"${ingresos_periodo:,.2f}")
            col_p2.metric("Egresos (Filtrados)", f"${gastos_periodo:,.2f}")
            col_p3.metric("Flujo Neto", f"${(ingresos_periodo - gastos_periodo):,.2f}")

        with col_radar:
            st.markdown(f"### 🎯 Radar de Pagos (Mes actual)")
            gastos_mes_actual = df[(df['Tipo'] == 'Gasto') & (df['Fecha'].dt.month == hoy.month) & (df['Fecha'].dt.year == hoy.year)]
            
            def check_radar(cat_exacta, keywords_incluir, keywords_excluir=None):
                mask = gastos_mes_actual['Categoría'] == cat_exacta
                if mask.sum() == 0: return False
                subset = gastos_mes_actual[mask]
                if not keywords_incluir and not keywords_excluir: return True
                for _, row in subset.iterrows():
                    texto = str(row['Concepto']).lower() + " " + str(row['Detalle']).lower()
                    incluye = True
                    if keywords_incluir: incluye = any(kw.lower() in texto for kw in keywords_incluir)
                    excluye = False
                    if keywords_excluir: excluye = any(kw.lower() in texto for kw in keywords_excluir)
                    if incluye and not excluye: return True
                return False

            radar_items = [
                {"nombre": "Luz (EEQ)", "cat": "servicios básicos", "inc": ["luz", "eeq"], "exc": []},
                {"nombre": "Agua", "cat": "servicios básicos", "inc": ["agua", "pisque"], "exc": []},
                {"nombre": "Internet Fasttnet", "cat": "servicios básicos", "inc": ["internet", "fasttnet"], "exc": []},
                {"nombre": "Asignación Laura", "cat": "asignación Laura", "inc": [], "exc": []},
                {"nombre": "Sueldo Julio", "cat": "sueldo (incluye FR)", "inc": [], "exc": []},
                {"nombre": "Planilla IESS (Aporte)", "cat": "IESS", "inc": [], "exc": []},
                {"nombre": "Préstamo IESS Julio", "cat": "Préstamo IESS", "inc": [], "exc": []}
            ]

            for item in radar_items:
                pagado = check_radar(item["cat"], item["inc"], item["exc"])
                if pagado: st.markdown(f"✅ **{item['nombre']}**")
                else: st.markdown(f"⚠️ **{item['nombre']}** (Pendiente)")
        
        st.markdown("---")
        col_chart1, col_chart2, col_chart3 = st.columns([2, 2, 1])
        with col_chart1:
            st.markdown(f"#### Flujo del Periodo Seleccionado")
            df_flujo = df_filtered.groupby([df_filtered['Fecha'].dt.to_period('M'), 'Tipo'])['Monto'].sum().reset_index()
            df_flujo['Fecha'] = df_flujo['Fecha'].astype(str)
            fig_bar = px.bar(df_flujo, x='Fecha', y='Monto', color='Tipo', barmode='group', color_discrete_map={'Ingreso':'#709b8b', 'Gasto':'#c9806b'})
            st.plotly_chart(fig_bar, width="stretch")
            
        with col_chart2:
            st.markdown("#### Distribución de Gastos")
            df_gastos = df_filtered[df_filtered['Tipo'] == 'Gasto']
            if not df_gastos.empty:
                fig_pie = px.pie(df_gastos, values='Monto', names='Categoría', hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
                st.plotly_chart(fig_pie, width="stretch")
            else:
                st.info("No hay gastos en este periodo/filtro.")
                
        with col_chart3:
            st.markdown("#### 💰 Provisiones")
            st.metric("Total Inmovilizado", f"${total_inmovilizado_global:,.2f}")
            df_resumen_prov = pd.DataFrame(datos_prov_global)
            st.dataframe(df_resumen_prov.style.format({'Acumulado': "${:,.2f}"}), hide_index=True, width="stretch")

        st.markdown("---")
        st.markdown("### 🕒 Últimos 5 Movimientos")
        if not df.empty:
            df_ultimos = df[df['Categoría'] != 'comisión banco'].copy()
            df_ultimos = df_ultimos.sort_values(by="Fecha", ascending=False).head(5)
            df_ultimos['Fecha'] = df_ultimos['Fecha'].dt.strftime('%d/%m/%Y')
            df_mostrar = df_ultimos[['Fecha', 'Tipo', 'Categoría', 'Concepto', 'Monto']]
            st.dataframe(df_mostrar.style.format({'Monto': "${:,.2f}"}), hide_index=True, width="stretch")
            
    else:
        st.info("Base de datos limpia. Registra tu primer movimiento.")
        st.metric("SALDO BANCARIO ACTUAL", f"${config['saldo_inicial']:,.2f}")

# --- TAB 2: REGISTRAR MOVIMIENTO ---
with tab2:
    st.markdown("### ⚡ Acciones Rápidas (Autocompletar)")
    
    col_q1, col_q2, col_q3, col_q4, col_q5 = st.columns(5)
    with col_q1:
        if st.button("💡 Luz (EEQ)"): set_quick_action('Gasto', 'servicios básicos', 'Pago Luz EEQ')
        if st.button("💧 Agua"): set_quick_action('Gasto', 'servicios básicos', 'Pago Agua')
    with col_q2:
        if st.button("🌐 Fasttnet"): set_quick_action('Gasto', 'servicios básicos', 'Pago Internet Fasttnet')
        if st.button("👩 Asignación Laura"): set_quick_action('Gasto', 'asignación Laura', 'Pago Asignación Laura')
    with col_q3:
        if st.button("🧑‍🔧 IESS (Planilla)"): set_quick_action('Gasto', 'IESS', 'Pago IESS')
        if st.button("🧑‍🔧 Préstamo IESS"): set_quick_action('Gasto', 'Préstamo IESS', 'Pago Préstamo IESS')
        if st.button("🧑‍🔧 Sueldo Julio"): set_quick_action('Gasto', 'sueldo (incluye FR)', 'Pago Sueldo Julio')
    with col_q4:
        st.write("**Descontar de Provisiones:**")
        if st.button("🎄 Pagar 13vo", type="primary"): set_quick_action('Gasto', 'varios', 'Pago 13vo (De Provisiones)', True, '13vo')
        if st.button("☀️ Pagar 14vo", type="primary"): set_quick_action('Gasto', 'varios', 'Pago 14vo (De Provisiones)', True, '14vo')
    with col_q5:
        st.write("**Descontar de Provisiones:**")
        if st.button("🏡 Pagar Prediales", type="primary"): set_quick_action('Gasto', 'Prediales - Impuestos', 'Pago Prediales (De Provisiones)', True, 'Prediales')
        if st.button("💧 Agua Pisque", type="primary"): set_quick_action('Gasto', 'varios', 'Pago Agua Pisque (De Provisiones)', True, 'Agua Pisque')

    st.markdown("---")
    st.markdown("### 📝 Ingreso de Movimiento")
    
    f_es_prov = st.session_state.form_data['es_prov']
    f_prov_key = st.session_state.form_data['prov_key']

    if f_es_prov: st.info(f"🟢 **Modo Provisión Activo:** El monto que guardes se descontará automáticamente del fondo de '{f_prov_key}'.")

    with st.form("form_nuevo_registro", clear_on_submit=False):
        col1, col2, col3 = st.columns(3)
        fecha_input = col1.date_input("Fecha", datetime.now().date(), key="reg_fecha")
        tipo_input = col2.selectbox("Tipo", ["Gasto", "Ingreso"], key="reg_tipo")
        categoria_input = col3.selectbox("Categoría", CATEGORIAS_EXACTAS, key="reg_cat")
        
        col4, col5, col6 = st.columns([1, 1, 2])
        monto_input = col4.number_input("Monto Principal ($)", min_value=0.0, format="%.2f", step=10.0, key="reg_monto")
        comision_input = col5.number_input("Comisión Banco ($) *Opcional*", min_value=0.0, format="%.2f", step=1.0, key="reg_comision")
        concepto_input = col6.text_input("Concepto (Breve descripción)", key="reg_concepto")
        
        detalle_input = st.text_input("Detalle adicional (Opcional)", key="reg_detalle")
        archivos_subidos = st.file_uploader("📎 Adjuntar comprobantes (Opcional)", accept_multiple_files=True, key="reg_archivos")
        confirmar_sin_adjunto = st.checkbox("⚠️ Confirmo que deseo registrar este movimiento **SIN comprobante adjunto**", key="reg_confirmar")
        
        submit_btn = st.form_submit_button("💾 GUARDAR MOVIMIENTO Y ENVIAR ALERTA", type="primary", width="stretch")
        
        if submit_btn:
            if monto_input <= 0 or not concepto_input:
                st.error("⚠️ El monto debe ser mayor a 0 y debes escribir un concepto.")
            elif not archivos_subidos and not confirmar_sin_adjunto:
                st.warning("✋ ALERTA: No has subido comprobante. Marca la casilla de arriba y vuelve a presionar Guardar.")
            else:
                nombres_archivos = []
                rutas_absolutas = []
                if archivos_subidos:
                    prefijo = datetime.now().strftime("%Y%m%d%H%M%S_")
                    for archivo in archivos_subidos:
                        nombre_seguro = prefijo + archivo.name
                        ruta_guardado = os.path.join(CARPETA_ADJUNTOS, nombre_seguro)
                        with open(ruta_guardado, "wb") as f: f.write(archivo.getbuffer())
                        nombres_archivos.append(nombre_seguro)
                        rutas_absolutas.append(ruta_guardado)
                
                string_adjuntos = "|".join(nombres_archivos)

                filas_a_guardar = [{
                    "Fecha": pd.to_datetime(fecha_input), "Tipo": tipo_input, "Categoría": categoria_input,
                    "Monto": monto_input, "Concepto": concepto_input, "Detalle": detalle_input, "Adjuntos": string_adjuntos
                }]
                if comision_input > 0:
                    filas_a_guardar.append({
                        "Fecha": pd.to_datetime(fecha_input), "Tipo": "Gasto", "Categoría": "comisión banco",
                        "Monto": comision_input, "Concepto": f"Comisión: {concepto_input}", "Detalle": "Generado automáticamente", "Adjuntos": ""
                    })
                    
                agregar_filas_a_tabla("master", filas_a_guardar)
                
                if f_es_prov and f_prov_key in config["provisiones"]:
                    nuevo_saldo_prov = float(config["provisiones"][f_prov_key]["acumulado"]) - float(monto_input)
                    config["provisiones"][f_prov_key]["acumulado"] = nuevo_saldo_prov
                    guardar_config(config)
                    agregar_filas_a_tabla("prov_hist", [{"Fecha": pd.to_datetime(fecha_input), "Rubro": f_prov_key, "Acumulado": nuevo_saldo_prov}])
                    st.success(f"¡Se descontaron ${monto_input:.2f} del fondo '{f_prov_key}'!")

                enviar_alerta(fecha_input, tipo_input, categoria_input, monto_input, concepto_input, detalle_input, rutas_absolutas, comision_input, config["destinatarios"])
                st.success("¡Registro guardado y correo enviado!")
                
                st.session_state.form_data = {'tipo': 'Gasto', 'cat': CATEGORIAS_EXACTAS[0], 'concepto': '', 'es_prov': False, 'prov_key': ''}
                for key in list(st.session_state.keys()):
                    if key.startswith("reg_"): del st.session_state[key]
                        
                st.cache_data.clear()
                st.rerun()

# --- TAB 3: EDITAR REGISTROS ---
with tab3:
    st.markdown("### Centro de Edición de Bases de Datos")
    
    with st.expander("⬇️ Descargar Bases de Datos en Excel (CSV)"):
        col_d1, col_d2, col_d3 = st.columns(3)
        col_d1.download_button("Descargar Master", data=df.to_csv(index=False), file_name="quinche_master.csv", mime="text/csv")
        col_d2.download_button("Descargar Inversiones", data=df_inv.to_csv(index=False), file_name="quinche_inversiones.csv", mime="text/csv")
        col_d3.download_button("Descargar CxC", data=df_act.to_csv(index=False), file_name="quinche_activos.csv", mime="text/csv")
        
    tabla_a_editar = st.selectbox("Selecciona la tabla que deseas corregir:", ["Movimientos Financieros", "Inversiones", "Cuentas por Cobrar"])
    st.info("💡 **Tip para guardar:** Presiona la tecla `Enter` tras modificar una celda ANTES de hacer clic en Guardar.")
    
    if tabla_a_editar == "Movimientos Financieros" and not df.empty:
        mask = (df['Fecha'] >= start_date) & (df['Fecha'] <= end_date) & df['Categoría'].isin(categorias_seleccionadas)
        df_edicion = df[mask].copy()
        edited_df = st.data_editor(df_edicion, num_rows="dynamic", width="stretch")
        
        if st.button("💾 Guardar Cambios en Movimientos"):
            edited_df['Fecha'] = pd.to_datetime(edited_df['Fecha'])
            df_fuera_filtro = df[~mask]
            df_final = pd.concat([df_fuera_filtro, edited_df], ignore_index=True)
            df_final.sort_values(by="Fecha", inplace=True)
            guardar_tabla("master", df_final)
            st.success("¡Historial actualizado de forma segura!")
            st.cache_data.clear()
            st.rerun()
            
        st.markdown("---")
        st.markdown("### 📧 Reenviar Comprobante")
        df_re = df[mask].copy().sort_values(by="Fecha", ascending=False).reset_index(drop=True)
        opciones_mail = [f"{i} | {pd.to_datetime(row['Fecha']).strftime('%d/%m/%Y') if pd.notna(row['Fecha']) else 'Sin Fecha'} - {row['Tipo']} - {row['Concepto']} (${row['Monto']:.2f}){(' 📎' if pd.notna(row.get('Adjuntos')) and row.get('Adjuntos') != '' else '')}" for i, row in df_re.iterrows()]
            
        if opciones_mail:
            seleccion = st.selectbox("Movimiento a reenviar:", opciones_mail)
            if st.button("📤 Reenviar Correo a Lista de Destinatarios"):
                row = df_re.iloc[int(seleccion.split(" |")[0])]
                rutas_a_reenviar = [os.path.join(CARPETA_ADJUNTOS, n) for n in str(row.get('Adjuntos', '')).split('|') if n.strip() and os.path.exists(os.path.join(CARPETA_ADJUNTOS, n))]
                if enviar_alerta(row['Fecha'], row['Tipo'], row['Categoría'], row['Monto'], row['Concepto'], row['Detalle'], rutas_a_reenviar, 0, config["destinatarios"]):
                    st.success("¡Correo reenviado exitosamente!")
                else: st.error("Hubo un problema al enviar el correo.")

    elif tabla_a_editar == "Inversiones" and not df_inv.empty:
        mask_inv = (df_inv['Fecha Inicio'] >= start_date) & (df_inv['Fecha Inicio'] <= end_date)
        edited_inv = st.data_editor(df_inv[mask_inv].copy(), num_rows="dynamic", width="stretch")
        if st.button("💾 Guardar Cambios en Inversiones"):
            edited_inv['Fecha Inicio'] = pd.to_datetime(edited_inv['Fecha Inicio'])
            df_inv_final = pd.concat([df_inv[~mask_inv], edited_inv], ignore_index=True)
            df_inv_final.sort_values(by="Fecha Inicio", inplace=True)
            guardar_tabla("inversiones", df_inv_final)
            st.success("¡Inversiones actualizadas!")
            st.cache_data.clear()
            st.rerun()
            
    elif tabla_a_editar == "Cuentas por Cobrar" and not df_act.empty:
        mask_act = (df_act['Fecha'] >= start_date) & (df_act['Fecha'] <= end_date)
        edited_act = st.data_editor(df_act[mask_act].copy(), num_rows="dynamic", width="stretch")
        if st.button("💾 Guardar Cambios en CxC"):
            edited_act['Fecha'] = pd.to_datetime(edited_act['Fecha'])
            df_act_final = pd.concat([df_act[~mask_act], edited_act], ignore_index=True)
            df_act_final.sort_values(by="Fecha", inplace=True)
            guardar_tabla("activos", df_act_final)
            st.success("¡Cuentas por Cobrar actualizadas!")
            st.cache_data.clear()
            st.rerun()

# --- TAB 4: PROVISIONES ---
with tab4:
    st.markdown("### 💰 Gestión y Cálculo de Provisiones")
    col_acc1, col_acc2 = st.columns([1, 1])
    with col_acc1: st.info(f"**Última aplicación de cuotas:** {config.get('ultima_aplicacion_prov', 'Nunca')}")
    with col_acc2:
        if st.button("➕ Aplicar Cuotas de este Mes", type="primary"):
            nuevos_registros = []
            fecha_hoy = datetime.now().strftime("%Y-%m-%d")
            for clave, data in config["provisiones"].items():
                nuevo_acumulado = float(data["acumulado"]) + float(data["mensual"])
                config["provisiones"][clave]["acumulado"] = nuevo_acumulado
                nuevos_registros.append({"Fecha": pd.to_datetime(fecha_hoy), "Rubro": clave, "Acumulado": nuevo_acumulado})
            config["ultima_aplicacion_prov"] = fecha_hoy
            guardar_config(config)
            agregar_filas_a_tabla("prov_hist", nuevos_registros)
            st.success("¡Provisiones actualizadas en el historial!")
            st.cache_data.clear()
            st.rerun()

    st.markdown("---")
    col_p1, col_p2 = st.columns([2, 1])
    with col_p1:
        st.markdown("#### Estado Actual del Fondo")
        datos_prov_full = [{"Rubro": k, "Detalle / Vencimiento": v["nota"], "Cuota Mensual": f"${float(v['mensual']):,.2f}", "Acumulado Actual": float(v["acumulado"])} for k, v in config["provisiones"].items()]
        st.dataframe(pd.DataFrame(datos_prov_full).style.format({'Acumulado Actual': "${:,.2f}"}), hide_index=True, width="stretch")
        st.markdown(f"### Total Fondo Inmovilizado: **${total_inmovilizado_global:,.2f}**")
        
        with st.expander("Ver Historial de Cierres Mensuales"):
            if not df_prov_hist.empty:
                df_prov_hist['Fecha'] = pd.to_datetime(df_prov_hist['Fecha']).dt.strftime('%Y-%m-%d')
                st.dataframe(df_prov_hist.sort_values(by="Fecha", ascending=False), hide_index=True, width="stretch")

    with col_p2:
        st.markdown("#### Ajuste Manual por Rubro")
        with st.form("form_ajuste_prov"):
            rubro_ajustar = st.selectbox("Rubro a ajustar", list(config["provisiones"].keys()))
            nuevo_base = st.number_input("Nuevo Acumulado Base ($)", value=float(config["provisiones"][rubro_ajustar]["acumulado"]))
            if st.form_submit_button("Actualizar Base"):
                config["provisiones"][rubro_ajustar]["acumulado"] = nuevo_base
                guardar_config(config)
                st.success("Base actualizada.")
                time.sleep(1)
                st.cache_data.clear()
                st.rerun()
                
        st.markdown("---")
        st.markdown("#### Ajuste de Saldo Bancario")
        flujo_historico_neto = df[df['Tipo'] == 'Ingreso']['Monto'].sum() - df[df['Tipo'] == 'Gasto']['Monto'].sum() if not df.empty else 0
        nuevo_saldo_actual = st.number_input("Saldo Bancario Real ($)", value=float(config["saldo_inicial"] + flujo_historico_neto), step=100.0)
        
        if st.button("🔄 Sincronizar Saldo Real"):
            config["saldo_inicial"] = nuevo_saldo_actual - flujo_historico_neto
            guardar_config(config)
            st.success("¡Saldo bancario sincronizado!")
            time.sleep(1)
            st.cache_data.clear()
            st.rerun()

# --- TAB 5: INVERSIONES ---
with tab5:
    st.markdown("### 📈 Portafolio de Inversiones")
    if not df_inv.empty: st.dataframe(df_inv, hide_index=True, width="stretch")
        
    col_inv1, col_inv2 = st.columns(2)
    with col_inv1:
        with st.expander("➕ Registrar Nueva Inversión", expanded=False):
            with st.form("form_inversion", clear_on_submit=True):
                inv_monto = st.number_input("Monto a Invertir ($)", min_value=0.0, format="%.2f")
                inv_entidad = st.text_input("Entidad")
                inv_tasa = st.number_input("Tasa Anual (%)", min_value=0.0, format="%.2f")
                col_i4, col_i5 = st.columns(2)
                inv_fecha = col_i4.date_input("Fecha de Inicio", datetime.now().date())
                inv_plazo = col_i5.number_input("Plazo (días)", min_value=1, step=1)
                gen_gasto_inv = st.checkbox("Generar automáticamente Gasto bajo 'Capital Invertido'", value=True)
                
                if st.form_submit_button("Guardar Inversión"):
                    vencimiento = inv_fecha + timedelta(days=inv_plazo)
                    interes = inv_monto * (inv_tasa / 100) * (inv_plazo / 365)
                    agregar_filas_a_tabla("inversiones", [{
                        "Fecha Inicio": pd.to_datetime(inv_fecha), "Entidad": inv_entidad, "Monto": inv_monto,
                        "Tasa Anual (%)": inv_tasa, "Plazo (días)": inv_plazo,
                        "Fecha Vencimiento": vencimiento.strftime('%Y-%m-%d'), "Interés Generado": round(interes, 2), "Estado": "Activa"
                    }])
                    
                    if gen_gasto_inv:
                        agregar_filas_a_tabla("master", [{
                            "Fecha": pd.to_datetime(inv_fecha), "Tipo": "Gasto", "Categoría": "capital invertido",
                            "Monto": inv_monto, "Concepto": f"Apertura Inversión: {inv_entidad}", "Detalle": f"Plazo: {inv_plazo} días a {inv_tasa}%", "Adjuntos": ""
                        }])
                    st.success(f"Inversión registrada. Vencimiento: {vencimiento.strftime('%d/%m/%Y')}")
                    st.cache_data.clear()
                    st.rerun()
                    
    with col_inv2:
        df_inv_activas = df_inv[df_inv['Estado'] == 'Activa'] if not df_inv.empty else pd.DataFrame()
        if not df_inv_activas.empty:
            with st.expander("🔄 Liquidar Inversión", expanded=True):
                with st.form("form_liquidar_inv"):
                    inv_sel = st.selectbox("Selecciona inversión a cerrar:", [f"{idx} | {row['Entidad']} - ${row['Monto']:.2f}" for idx, row in df_inv_activas.iterrows()])
                    if st.form_submit_button("Liquidar (Recuperar Capital e Intereses)"):
                        idx_real = int(inv_sel.split(" |")[0])
                        row_inv = df_inv.loc[idx_real]
                        df_inv.at[idx_real, 'Estado'] = 'Finalizada'
                        guardar_tabla("inversiones", df_inv)
                        
                        filas_ingreso = [{
                            "Fecha": pd.to_datetime(datetime.now().date()), "Tipo": "Ingreso", "Categoría": "capital invertido",
                            "Monto": row_inv['Monto'], "Concepto": f"Retorno Capital: {row_inv['Entidad']}", "Detalle": "Liquidación finalizada", "Adjuntos": ""
                        }]
                        if row_inv['Interés Generado'] > 0:
                            filas_ingreso.append({
                                "Fecha": pd.to_datetime(datetime.now().date()), "Tipo": "Ingreso", "Categoría": "intereses recibidos",
                                "Monto": row_inv['Interés Generado'], "Concepto": f"Intereses: {row_inv['Entidad']}", "Detalle": "Liquidación finalizada", "Adjuntos": ""
                            })
                        agregar_filas_a_tabla("master", filas_ingreso)
                        st.success("¡Inversión liquidada exitosamente!")
                        st.cache_data.clear()
                        st.rerun()

# --- TAB 6: CUENTAS POR COBRAR ---
with tab6:
    st.markdown("### 🤝 Activos y Cuentas por Cobrar")
    if not df_act.empty: st.dataframe(df_act, hide_index=True, width="stretch")
    
    col_cxc1, col_cxc2 = st.columns(2)
    with col_cxc1:
        with st.expander("➕ Registrar Nueva CxC", expanded=False):
            with st.form("form_cxc", clear_on_submit=True):
                cxc_fecha = st.date_input("Fecha emisión", datetime.now().date())
                cxc_deudor = st.text_input("Deudor")
                cxc_monto = st.number_input("Monto a Cobrar ($)", min_value=0.0, format="%.2f")
                cxc_concepto = st.text_input("Concepto")
                cxc_esperada = st.date_input("Fecha Esperada de Pago")
                
                if st.form_submit_button("Guardar"):
                    agregar_filas_a_tabla("activos", [{
                        "Fecha": cxc_fecha.strftime('%Y-%m-%d'), "Deudor": cxc_deudor, "Concepto": cxc_concepto,
                        "Monto": cxc_monto, "Fecha Esperada": cxc_esperada.strftime('%Y-%m-%d'), "Estado": "Pendiente"
                    }])
                    st.success("Cuenta registrada.")
                    st.cache_data.clear()
                    st.rerun()

    with col_cxc2:
        df_pendientes = df_act[df_act['Estado'] == 'Pendiente'] if not df_act.empty else pd.DataFrame()
        if not df_pendientes.empty:
            with st.expander("🔄 Liquidar o Condonar", expanded=True):
                with st.form("form_liquidar"):
                    cuenta_sel = st.selectbox("Selecciona cuenta:", [f"{idx} | {row['Deudor']} (${row['Monto']:.2f})" for idx, row in df_pendientes.iterrows()])
                    accion = st.radio("Acción:", ["Registrar como Pagada (Generar Ingreso)", "Condonar / Anular"])
                    cat_ingreso = st.selectbox("Categoría de Ingreso:", ["varios", "intereses recibidos", "inversión", "alquiler", "venta de aguacates"])
                    
                    if st.form_submit_button("Ejecutar"):
                        idx_real = int(cuenta_sel.split(" |")[0])
                        row_cxc = df_act.loc[idx_real]
                        if "Pagada" in accion:
                            df_act.at[idx_real, 'Estado'] = 'Pagado'
                            guardar_tabla("activos", df_act)
                            agregar_filas_a_tabla("master", [{
                                "Fecha": pd.to_datetime(datetime.now().date()), "Tipo": "Ingreso", "Categoría": cat_ingreso,
                                "Monto": row_cxc['Monto'], "Concepto": f"Cobro: {row_cxc['Deudor']}", "Detalle": row_cxc['Concepto'], "Adjuntos": ""
                            }])
                            st.success("¡Cuenta pagada y registrada en ingresos!")
                        else:
                            df_act.at[idx_real, 'Estado'] = 'Condonado/Anulado'
                            guardar_tabla("activos", df_act)
                            st.success("Cuenta condonada.")
                        st.cache_data.clear()
                        st.rerun()

# --- TAB 7: CALCULADORA NÓMINA ---
with tab7:
    st.markdown("### 🧑‍🔧 Calculadora de Nómina - Julio Imbacuán")
    col_n1, col_n2 = st.columns(2)
    with col_n1:
        st.metric("Salario Básico", "$482.00")
        st.metric("Fondo de Reserva (8.33%)", "$40.17")
        st.metric("Total a Recibir (Bruto)", "$522.17")
    with col_n2:
        prestamo_iess = st.number_input("Préstamo IESS a descontar ($)", min_value=0.0, format="%.2f")
        valor_depositar = 522.17 - prestamo_iess
        st.markdown("---")
        st.markdown(f"<h2 style='color: #709b8b;'>Valor Final a Depositar: ${valor_depositar:,.2f}</h2>", unsafe_allow_html=True)
        
        if st.button("Generar registro en Movimientos"):
            filas = []
            if prestamo_iess > 0:
                filas.append({
                    "Fecha": pd.to_datetime(datetime.now().date()), "Tipo": "Gasto", "Categoría": "Préstamo IESS",
                    "Monto": prestamo_iess, "Concepto": "Pago Préstamo IESS Julio", "Detalle": "Descuento de rol", "Adjuntos": ""
                })
            filas.append({
                "Fecha": pd.to_datetime(datetime.now().date()), "Tipo": "Gasto", "Categoría": "sueldo (incluye FR)",
                "Monto": valor_depositar, "Concepto": "Sueldo Neto Julio Imbacuán", "Detalle": f"Bruto menos ${prestamo_iess:.2f}", "Adjuntos": ""
            })
            agregar_filas_a_tabla("master", filas)
            st.success("¡Registros generados exitosamente!")
            st.cache_data.clear()
            st.rerun()

# --- TAB 8: GESTIÓN DE CORREOS ---
with tab8:
    st.markdown("### 📧 Gestión de Destinatarios de Alertas")
    destinatarios_actuales = config.get("destinatarios", [])
    predefinidos_activos = [c for c in destinatarios_actuales if c in CORREOS_PREDEFINIDOS]
    otros_str = ", ".join([c for c in destinatarios_actuales if c not in CORREOS_PREDEFINIDOS])

    with st.form("form_correos"):
        seleccion_predefinidos = st.multiselect("Correos Frecuentes", options=CORREOS_PREDEFINIDOS, default=predefinidos_activos)
        otros_input = st.text_area("Otros correos temporales (Separados por coma):", value=otros_str)
        
        if st.form_submit_button("💾 Guardar Configuración de Correos"):
            otros_lista = [c.strip() for c in otros_input.split(",") if c.strip()]
            lista_final = []
            for correo in (seleccion_predefinidos + otros_lista):
                if correo not in lista_final: lista_final.append(correo)
            
            config["destinatarios"] = lista_final
            guardar_config(config)
            st.success("¡Lista de destinatarios actualizada exitosamente!")
            time.sleep(1)
            st.cache_data.clear()
            st.rerun()

# --- TAB 9: ASISTENTE IA ---
with tab9:
    col_ia1, col_ia2 = st.columns([4, 1])
    with col_ia1:
        st.markdown("### 🤖 Asistente Financiero de El Quinche")
        st.write("Pregúntame directamente sobre tus movimientos, gastos, ingresos, inversiones o provisiones.")
    with col_ia2:
        if st.button("🗑️ Borrar Historial", width="stretch"):
            st.session_state.messages_ai = []
            st.rerun()
            
    if "messages_ai" not in st.session_state:
        st.session_state.messages_ai = []
        
    for message in st.session_state.messages_ai:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            
    if prompt := st.chat_input("Ej: ¿Cuánto he gastado en servicios básicos en febrero?"):
        st.session_state.messages_ai.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
            
        with st.chat_message("assistant"):
            try:
                if not df.empty:
                    df_ia = df[['Fecha', 'Tipo', 'Categoría', 'Monto', 'Concepto']].copy()
                    df_ia['Fecha'] = pd.to_datetime(df_ia['Fecha']).dt.strftime('%Y-%m-%d')
                    csv_master = df_ia.to_csv(index=False)
                else:
                    csv_master = "No hay registros en la base de datos maestra."
                    
                csv_inv = df_inv[['Fecha Inicio', 'Entidad', 'Monto', 'Estado']].to_csv(index=False) if not df_inv.empty else "No hay inversiones registradas."
                csv_prov = pd.DataFrame(datos_prov_global).to_csv(index=False) if datos_prov_global else "No hay provisiones registradas."

                client = Groq(api_key=st.secrets["GROQ_API_KEY"])
                system_prompt = f"""
                Eres el analista de datos y asistente financiero del dashboard 'El Quinche'. 
                Tu misión es responder las dudas del usuario basándote ESTRICTAMENTE en los datos CSV que se te proporcionan a continuación.
                
                DATOS DE MOVIMIENTOS (Ingresos y Gastos):
                {csv_master}
                
                DATOS DE INVERSIONES:
                {csv_inv}
                
                FONDOS DE PROVISIONES:
                {csv_prov}
                
                REGLAS IMPORTANTES Y PROHIBICIONES ABSOLUTAS:
                1. TIENES PROHIBIDO TAJANTEMENTE hablar, discutir o responder sobre CUALQUIER tema que no esté estrictamente relacionado con este dashboard financiero, los datos proporcionados, finanzas o contabilidad del proyecto 'El Quinche'. Si el usuario pregunta sobre programación, historia, recetas, chistes o cualquier otra cosa fuera de contexto, debes negarte educada pero firmemente.
                2. NO le digas al usuario cómo usar el dashboard. Lee tú mismo los datos y dale la respuesta final.
                3. Si te preguntan por un mes o categoría, filtra mentalmente el archivo CSV, suma los montos y entrégale el valor exacto.
                4. Sé amigable, directo y claro.
                5. Responde siempre en español.
                """
                
                messages_to_send = [{"role": "system", "content": system_prompt}] + st.session_state.messages_ai
                
                completion = client.chat.completions.create(
                    model="llama-3.3-70b-versatile", 
                    messages=messages_to_send,
                    temperature=0.1, 
                    max_tokens=600,
                )
                
                response = completion.choices[0].message.content
                st.markdown(response)
                st.session_state.messages_ai.append({"role": "assistant", "content": response})
                
            except Exception as e:
                st.error(f"Error de conexión con la IA: {e}")