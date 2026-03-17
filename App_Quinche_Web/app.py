import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import os
import json
import sqlite3
from groq import Groq

# ==========================================
# CONFIGURACIÓN SEGURA (SOLO IA)
# ==========================================
GROQ_API_KEY = st.secrets["GROQ_API_KEY"] [cite: 49]

# ==========================================
# LECTURA DE BASE DE DATOS (SOLO LECTURA)
# ==========================================
DB_NAME = "quinche_data.db" [cite: 49]
ARCHIVO_CONFIG = "quinche_config.json" [cite: 49]

def cargar_tabla(nombre_tabla):
    try:
        conn = sqlite3.connect(DB_NAME) [cite: 49]
        df = pd.read_sql_query(f"SELECT * FROM {nombre_tabla}", conn) [cite: 49]
        conn.close() [cite: 49]
        for col in ['Fecha', 'Fecha Inicio', 'Fecha Esperada', 'Fecha Vencimiento']:
            if col in df.columns: df[col] = pd.to_datetime(df[col], errors='coerce') [cite: 49]
        for col in ['Monto', 'Acumulado', 'Interés Generado']:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0) [cite: 49]
        return df
    except Exception:
        return pd.DataFrame() [cite: 49]

df = cargar_tabla("master") [cite: 49]
df_inv = cargar_tabla("inversiones") [cite: 49]
df_act = cargar_tabla("activos") [cite: 49]

def cargar_config():
    default_config = {
        "saldo_inicial": 0.0, 
        "provisiones": {
            "Garantía": {"acumulado": 3055.51}, "13vo": {"acumulado": 112.50}, 
            "14vo": {"acumulado": 262.50}, "Prediales": {"acumulado": 230.00}, 
            "Agua Pisque": {"acumulado": 13.33}, "Reserva Varios": {"acumulado": 898.95}
        }
    } [cite: 49]
    if os.path.exists(ARCHIVO_CONFIG):
        with open(ARCHIVO_CONFIG, 'r') as f:
            data = json.load(f) [cite: 49]
            if "provisiones" not in data: data["provisiones"] = default_config["provisiones"]
            return data
    return default_config [cite: 49]

config = cargar_config() [cite: 49]
datos_prov_global = [{"Rubro": k, "Acumulado": float(v["acumulado"])} for k, v in config["provisiones"].items()] [cite: 49]
total_inmovilizado_global = sum(d["Acumulado"] for d in datos_prov_global) [cite: 49]

# ==========================================
# INTERFAZ DE USUARIO (VISUALIZADOR)
# ==========================================
# CAMBIO 3: initial_sidebar_state="expanded" hace que los filtros sean visibles de inmediato
st.set_page_config(
    page_title="Dashboard Quinche", 
    layout="wide", 
    initial_sidebar_state="expanded" 
) [cite: 49]

st.markdown("""
<style>
    [data-testid="stMetric"] { padding: 15px 20px; border-radius: 12px; border: 1px solid rgba(128, 128, 128, 0.2); background-color: #f9fbfb;}
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { border-radius: 8px 8px 0 0; }
</style>
""", unsafe_allow_html=True) [cite: 49]

st.title("📊 Panel Financiero - El Quinche (Visor)") [cite: 49]
st.info("🔒 Esta es una versión de acceso público y solo lectura. Los datos están protegidos.") [cite: 49]

CATEGORIAS_EXACTAS = [
    "sueldo (incluye FR)", "intereses recibidos", "inversión", "capital invertido", "alquiler", 
    "venta de aguacates", "servicios básicos", "infraestructura", 
    "mantenimiento de propiedad y equipos", "jardinería y exteriores", 
    "IESS", "Préstamo IESS", "gasolina aceite", "asignación Laura", "comisión banco", 
    "Prediales - Impuestos", "varios"
] [cite: 49]

if 'filtro_categorias' not in st.session_state: st.session_state.filtro_categorias = CATEGORIAS_EXACTAS.copy() [cite: 49]

def select_all_cats(): st.session_state.filtro_categorias = CATEGORIAS_EXACTAS.copy()
def clear_all_cats(): st.session_state.filtro_categorias = []

# --- FILTROS LATERALES ---
st.sidebar.markdown("### 📅 Filtros de Visualización") [cite: 49]
opcion_fecha = st.sidebar.radio("Periodo de análisis:", ["Este Mes", "Este Año", "Todo el Historial", "Personalizado"]) [cite: 49]
hoy = datetime.now().date() [cite: 49]

if opcion_fecha == "Este Mes": 
    start_date, end_date = pd.to_datetime(hoy.replace(day=1)), pd.to_datetime(hoy) [cite: 49]
elif opcion_fecha == "Este Año": 
    start_date, end_date = pd.to_datetime(hoy.replace(month=1, day=1)), pd.to_datetime(hoy) [cite: 49]
elif opcion_fecha == "Personalizado":
    rango = st.sidebar.date_input("Selecciona el rango:", [hoy - timedelta(days=30), hoy]) [cite: 49]
    start_date, end_date = pd.to_datetime(rango[0]), pd.to_datetime(rango[1] if len(rango)==2 else hoy) [cite: 49]
else: 
    start_date = df['Fecha'].min() if not df.empty else pd.to_datetime(hoy) [cite: 49]
    end_date = pd.to_datetime(hoy) [cite: 49]

st.sidebar.markdown("---")
st.sidebar.markdown("### 🏷️ Filtrar por Categoría")
col_btn1, col_btn2 = st.sidebar.columns(2) [cite: 49]
col_btn1.button("✅ Todas", on_click=select_all_cats)
col_btn2.button("❌ Ninguna", on_click=clear_all_cats)
categorias_seleccionadas = st.sidebar.multiselect("Categorías visibles:", options=CATEGORIAS_EXACTAS, key='filtro_categorias') [cite: 49]

# CAMBIO 1: Nombre de la pestaña actualizado a "Detalle de Movimientos"
tab1, tab2, tab3 = st.tabs(["📊 Dashboard Principal", "🗂️ Detalle de Movimientos", "🤖 Asistente IA"]) [cite: 49]

# --- TAB 1: DASHBOARD ---
with tab1:
    if not df.empty:
        df_filtered = df[(df['Fecha'] >= start_date) & (df['Fecha'] <= end_date) & (df['Categoría'].isin(categorias_seleccionadas))] [cite: 49]
        
        saldo_real_actual = config["saldo_inicial"] + df[df['Tipo'] == 'Ingreso']['Monto'].sum() - df[df['Tipo'] == 'Gasto']['Monto'].sum() [cite: 49]
        ingresos_periodo = df_filtered[df_filtered['Tipo'] == 'Ingreso']['Monto'].sum() [cite: 49]
        gastos_periodo = df_filtered[df_filtered['Tipo'] == 'Gasto']['Monto'].sum() [cite: 49]
        total_inversiones = df_inv[df_inv['Estado'] == 'Activa']['Monto'].sum() if not df_inv.empty else 0.0 [cite: 49]
        total_cxc = df_act[df_act['Estado'] == 'Pendiente']['Monto'].sum() if not df_act.empty else 0.0 [cite: 49]

        st.markdown("### 🏦 Resumen de Liquidez y Activos Histórico") [cite: 49]
        col1, col2, col3, col4 = st.columns(4) [cite: 49]
        col1.metric("SALDO BANCARIO ACTUAL", f"${saldo_real_actual:,.2f}") [cite: 49]
        col2.metric("Inversiones Activas", f"${total_inversiones:,.2f}") [cite: 49]
        col3.metric("Activos (Préstamos)", f"${total_cxc:,.2f}") [cite: 49]
        col4.metric("Patrimonio Líquido Total", f"${saldo_real_actual + total_inversiones + total_cxc:,.2f}") [cite: 49]
        
        st.markdown("---")
        col_resumen, col_radar = st.columns([2, 1]) [cite: 49]
        with col_resumen:
            st.markdown(f"### 🗓️ Resumen del Periodo ({start_date.strftime('%d/%m/%Y')} al {end_date.strftime('%d/%m/%Y')})") [cite: 49]
            cp1, cp2, cp3 = st.columns(3) [cite: 49]
            cp1.metric("Ingresos (Filtrados)", f"${ingresos_periodo:,.2f}") [cite: 49]
            cp2.metric("Egresos (Filtrados)", f"${gastos_periodo:,.2f}") [cite: 49]
            cp3.metric("Flujo Neto", f"${(ingresos_periodo - gastos_periodo):,.2f}") [cite: 49]

        with col_radar:
            st.markdown("### 🎯 Radar de Pagos (Mes actual)") [cite: 49]
            gastos_mes_actual = df[(df['Tipo'] == 'Gasto') & (df['Fecha'].dt.month == hoy.month) & (df['Fecha'].dt.year == hoy.year)] [cite: 49]
            def check_radar(cat_exacta, inc):
                mask = gastos_mes_actual['Categoría'] == cat_exacta [cite: 49]
                if mask.sum() == 0: return False
                for _, r in gastos_mes_actual[mask].iterrows():
                    txt = str(r['Concepto']).lower() + " " + str(r['Detalle']).lower() [cite: 49]
                    if not inc or any(k.lower() in txt for k in inc): return True
                return False
            
            radar_items = [
                {"n": "Luz (EEQ)", "c": "servicios básicos", "i": ["luz", "eeq"]}, 
                {"n": "Agua", "c": "servicios básicos", "i": ["agua", "pisque"]}, 
                {"n": "Internet", "c": "servicios básicos", "i": ["internet", "fasttnet"]}, 
                {"n": "Asig. Laura", "c": "asignación Laura", "i": []}, 
                {"n": "Sueldo Julio", "c": "sueldo (incluye FR)", "i": []}, 
                {"n": "IESS", "c": "IESS", "i": []}, 
                {"n": "Préstamo IESS", "c": "Préstamo IESS", "i": []}
            ] [cite: 49]
            for item in radar_items:
                st.markdown(f"✅ **{item['n']}**" if check_radar(item['c'], item['i']) else f"⚠️ **{item['n']}** (Pendiente)") [cite: 49]
        
        st.markdown("---")
        col_chart1, col_chart2, col_chart3 = st.columns([2, 2, 1]) [cite: 49]
        with col_chart1:
            st.markdown("#### Flujo del Periodo Seleccionado") [cite: 49]
            if not df_filtered.empty:
                df_flujo = df_filtered.groupby([df_filtered['Fecha'].dt.to_period('M'), 'Tipo'])['Monto'].sum().reset_index() [cite: 49]
                df_flujo['Fecha'] = df_flujo['Fecha'].astype(str) [cite: 49]
                st.plotly_chart(px.bar(df_flujo, x='Fecha', y='Monto', color='Tipo', barmode='group', color_discrete_map={'Ingreso':'#709b8b', 'Gasto':'#c9806b'}), width="stretch") [cite: 49]
        
        with col_chart2:
            st.markdown("#### Distribución de Gastos") [cite: 49]
            df_gastos = df_filtered[df_filtered['Tipo'] == 'Gasto'] [cite: 49]
            if not df_gastos.empty: 
                st.plotly_chart(px.pie(df_gastos, values='Monto', names='Categoría', hole=0.4), width="stretch") [cite: 49]
            else: 
                st.info("No hay gastos registrados en este periodo.") [cite: 49]
        
        with col_chart3:
            st.markdown("#### 💰 Provisiones") [cite: 49]
            st.metric("Total Inmovilizado", f"${total_inmovilizado_global:,.2f}") [cite: 49]
            st.dataframe(pd.DataFrame(datos_prov_global).style.format({'Acumulado': "${:,.2f}"}), hide_index=True, width="stretch") [cite: 49]

        st.markdown("---")
        st.markdown("### 🕒 Últimos 5 Movimientos") [cite: 49]
        df_ultimos = df[df['Categoría'] != 'comisión banco'].sort_values(by="Fecha", ascending=False).head(5).copy() [cite: 49]
        df_ultimos['Fecha'] = df_ultimos['Fecha'].dt.strftime('%d/%m/%Y') [cite: 49]
        st.dataframe(df_ultimos[['Fecha', 'Tipo', 'Categoría', 'Concepto', 'Monto']].style.format({'Monto': "${:,.2f}"}), hide_index=True, width="stretch") [cite: 49]
    else: 
        st.warning("No se encontraron datos.") [cite: 49]

# --- TAB 2: VISTA DE BASES DE DATOS ---
with tab2:
    st.markdown("### 🗂️ Explorador de Datos (Solo Lectura)") [cite: 49]
    tabla_ver = st.selectbox("Selecciona la base de datos a explorar:", ["Movimientos Financieros", "Portafolio de Inversiones", "Cuentas por Cobrar"]) [cite: 49]
    
    if tabla_ver == "Movimientos Financieros" and not df.empty:
        df_show = df.sort_values(by="Fecha", ascending=False).copy() [cite: 49]
        df_show['Fecha'] = df_show['Fecha'].dt.strftime('%d/%m/%Y') [cite: 49]
        st.dataframe(df_show, width="stretch", hide_index=True) [cite: 49]
    elif tabla_ver == "Portafolio de Inversiones" and not df_inv.empty:
        df_inv_show = df_inv.copy() [cite: 49]
        df_inv_show['Fecha Inicio'] = df_inv_show['Fecha Inicio'].dt.strftime('%d/%m/%Y') [cite: 49]
        st.dataframe(df_inv_show, width="stretch", hide_index=True) [cite: 49]
    elif tabla_ver == "Cuentas por Cobrar" and not df_act.empty:
        df_act_show = df_act.copy() [cite: 49]
        df_act_show['Fecha'] = df_act_show['Fecha'].dt.strftime('%d/%m/%Y') [cite: 49]
        st.dataframe(df_act_show, width="stretch", hide_index=True) [cite: 49]

# --- TAB 3: ASISTENTE AI ---
with tab3:
    col_ia1, col_ia2 = st.columns([4, 1]) [cite: 49]
    with col_ia1:
        st.markdown("### 🤖 Asistente Financiero AI") [cite: 49]
        st.write("Analizo las bases de datos de El Quinche para responder tus dudas.") [cite: 49]
    with col_ia2:
        # CAMBIO 2: Nombre del botón más amigable
        if st.button("🧼 Limpiar pantalla", width="stretch"):
            st.session_state.messages_ai = []
            st.rerun() [cite: 49]

    if "messages_ai" not in st.session_state: st.session_state.messages_ai = [] [cite: 49]

    for message in st.session_state.messages_ai:
        with st.chat_message(message["role"]): st.markdown(message["content"]) [cite: 49]

    if prompt := st.chat_input("Ej: ¿Cuánto he gastado en servicios básicos este año?"):
        st.session_state.messages_ai.append({"role": "user", "content": prompt}) [cite: 49]
        with st.chat_message("user"): st.markdown(prompt) [cite: 49]

        with st.chat_message("assistant"):
            try:
                with st.spinner('Analizando los datos...'): [cite: 49]
                    if not df.empty:
                        df_ia = df[['Fecha', 'Tipo', 'Categoría', 'Monto', 'Concepto']].copy() [cite: 49]
                        df_ia['Fecha'] = pd.to_datetime(df_ia['Fecha']).dt.strftime('%Y-%m-%d') [cite: 49]
                        csv_master = df_ia.to_csv(index=False) [cite: 49]
                    else: csv_master = "Sin registros." [cite: 49]

                    csv_inv = df_inv[['Fecha Inicio', 'Entidad', 'Monto', 'Estado']].to_csv(index=False) if not df_inv.empty else "Sin inversiones." [cite: 49]
                    csv_prov = pd.DataFrame(datos_prov_global).to_csv(index=False) if datos_prov_global else "Sin provisiones." [cite: 49]
                    saldo_str = f"SALDO BANCARIO ACTUAL: ${saldo_real_actual:.2f}\n" if 'saldo_real_actual' in locals() else "" [cite: 49]

                    client = Groq(api_key=GROQ_API_KEY) [cite: 49]
                    system_prompt = f"Eres el analista financiero de 'El Quinche'. Responde usando estos datos:\n{csv_master}\n{csv_inv}\n{csv_prov}\n{saldo_str}\nReglas: Solo temas financieros de este proyecto. Sé directo y usa $." [cite: 49]

                    messages_to_send = [{"role": "system", "content": system_prompt}] + st.session_state.messages_ai [cite: 49]
                    completion = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=messages_to_send, temperature=0.1, max_tokens=600) [cite: 49]

                    response = completion.choices[0].message.content [cite: 49]
                    st.markdown(response) [cite: 49]
                    st.session_state.messages_ai.append({"role": "assistant", "content": response}) [cite: 49]
            except Exception as e: st.error(f"Error: {e}") [cite: 49]