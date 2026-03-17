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
# En la nube (Streamlit Community Cloud), esta llave se lee desde los "Secrets"
GROQ_API_KEY = st.secrets["GROQ_API_KEY"]

# ==========================================
# LECTURA DE BASE DE DATOS (SOLO LECTURA)
# ==========================================
DB_NAME = "quinche_data.db"
ARCHIVO_CONFIG = "quinche_config.json"

def cargar_tabla(nombre_tabla):
    try:
        conn = sqlite3.connect(DB_NAME)
        df = pd.read_sql_query(f"SELECT * FROM {nombre_tabla}", conn)
        conn.close()
        for col in ['Fecha', 'Fecha Inicio', 'Fecha Esperada', 'Fecha Vencimiento']:
            if col in df.columns: df[col] = pd.to_datetime(df[col], errors='coerce')
        for col in ['Monto', 'Acumulado', 'Interés Generado']:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
        return df
    except Exception:
        # Retorna un DataFrame vacío si no encuentra la tabla o hay error
        return pd.DataFrame()

df = cargar_tabla("master")
df_inv = cargar_tabla("inversiones")
df_act = cargar_tabla("activos")

# Configuración de provisiones y saldo (Lectura)
def cargar_config():
    default_config = {
        "saldo_inicial": 0.0, 
        "provisiones": {
            "Garantía": {"acumulado": 3055.51}, "13vo": {"acumulado": 112.50}, 
            "14vo": {"acumulado": 262.50}, "Prediales": {"acumulado": 230.00}, 
            "Agua Pisque": {"acumulado": 13.33}, "Reserva Varios": {"acumulado": 898.95}
        }
    }
    if os.path.exists(ARCHIVO_CONFIG):
        with open(ARCHIVO_CONFIG, 'r') as f:
            data = json.load(f)
            if "provisiones" not in data: data["provisiones"] = default_config["provisiones"]
            return data
    return default_config

config = cargar_config()
datos_prov_global = [{"Rubro": k, "Acumulado": float(v["acumulado"])} for k, v in config["provisiones"].items()]
total_inmovilizado_global = sum(d["Acumulado"] for d in datos_prov_global)

# ==========================================
# INTERFAZ DE USUARIO (VISUALIZADOR)
# ==========================================
st.set_page_config(page_title="Dashboard Quinche", layout="wide")

st.markdown("""
<style>
    [data-testid="stMetric"] { padding: 15px 20px; border-radius: 12px; border: 1px solid rgba(128, 128, 128, 0.2); background-color: #f9fbfb;}
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { border-radius: 8px 8px 0 0; }
</style>
""", unsafe_allow_html=True)

st.title("📊 Panel Financiero - El Quinche (Visor)")
st.info("🔒 Esta es una versión de acceso público y solo lectura. Ningún dato puede ser alterado o eliminado desde esta interfaz.")

CATEGORIAS_EXACTAS = [
    "sueldo (incluye FR)", "intereses recibidos", "inversión", "capital invertido", "alquiler", 
    "venta de aguacates", "servicios básicos", "infraestructura", 
    "mantenimiento de propiedad y equipos", "jardinería y exteriores", 
    "IESS", "Préstamo IESS", "gasolina aceite", "asignación Laura", "comisión banco", 
    "Prediales - Impuestos", "varios"
]

if 'filtro_categorias' not in st.session_state: st.session_state.filtro_categorias = CATEGORIAS_EXACTAS.copy()

def select_all_cats(): st.session_state.filtro_categorias = CATEGORIAS_EXACTAS.copy()
def clear_all_cats(): st.session_state.filtro_categorias = []

# --- FILTROS LATERALES ---
st.sidebar.markdown("### 📅 Filtros de Visualización")
opcion_fecha = st.sidebar.radio("Periodo de análisis:", ["Este Mes", "Este Año", "Todo el Historial", "Personalizado"])
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
    end_date = pd.to_datetime(hoy)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🏷️ Filtrar por Categoría")
col_btn1, col_btn2 = st.sidebar.columns(2)
col_btn1.button("✅ Todas", on_click=select_all_cats)
col_btn2.button("❌ Ninguna", on_click=clear_all_cats)
categorias_seleccionadas = st.sidebar.multiselect("Categorías visibles:", options=CATEGORIAS_EXACTAS, key='filtro_categorias')

# PESTAÑAS SIMPLIFICADAS
tab1, tab2, tab3 = st.tabs(["📊 Dashboard Principal", "🗂️ Desglose de Bases de Datos", "🤖 Asistente AI"])

# --- TAB 1: DASHBOARD ---
with tab1:
    if not df.empty:
        df_filtered = df[(df['Fecha'] >= start_date) & (df['Fecha'] <= end_date) & (df['Categoría'].isin(categorias_seleccionadas))]
        
        saldo_real_actual = config["saldo_inicial"] + df[df['Tipo'] == 'Ingreso']['Monto'].sum() - df[df['Tipo'] == 'Gasto']['Monto'].sum()
        ingresos_periodo = df_filtered[df_filtered['Tipo'] == 'Ingreso']['Monto'].sum()
        gastos_periodo = df_filtered[df_filtered['Tipo'] == 'Gasto']['Monto'].sum()
        total_inversiones = df_inv[df_inv['Estado'] == 'Activa']['Monto'].sum() if not df_inv.empty else 0.0
        total_cxc = df_act[df_act['Estado'] == 'Pendiente']['Monto'].sum() if not df_act.empty else 0.0

        st.markdown("### 🏦 Resumen de Liquidez y Activos Histórico")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("SALDO BANCARIO ACTUAL", f"${saldo_real_actual:,.2f}")
        col2.metric("Inversiones Activas", f"${total_inversiones:,.2f}")
        col3.metric("Activos (Préstamos)", f"${total_cxc:,.2f}")
        col4.metric("Patrimonio Líquido Total", f"${saldo_real_actual + total_inversiones + total_cxc:,.2f}")
        
        st.markdown("---")
        col_resumen, col_radar = st.columns([2, 1])
        with col_resumen:
            st.markdown(f"### 🗓️ Resumen del Periodo ({start_date.strftime('%d/%m/%Y')} al {end_date.strftime('%d/%m/%Y')})")
            cp1, cp2, cp3 = st.columns(3)
            cp1.metric("Ingresos (Filtrados)", f"${ingresos_periodo:,.2f}")
            cp2.metric("Egresos (Filtrados)", f"${gastos_periodo:,.2f}")
            cp3.metric("Flujo Neto", f"${(ingresos_periodo - gastos_periodo):,.2f}")

        with col_radar:
            st.markdown("### 🎯 Radar de Pagos (Mes actual)")
            gastos_mes_actual = df[(df['Tipo'] == 'Gasto') & (df['Fecha'].dt.month == hoy.month) & (df['Fecha'].dt.year == hoy.year)]
            def check_radar(cat_exacta, inc, exc=None):
                mask = gastos_mes_actual['Categoría'] == cat_exacta
                if mask.sum() == 0: return False
                for _, r in gastos_mes_actual[mask].iterrows():
                    txt = str(r['Concepto']).lower() + " " + str(r['Detalle']).lower()
                    if (not inc or any(k.lower() in txt for k in inc)) and (not exc or not any(k.lower() in txt for k in exc)): return True
                return False
            
            radar_items = [
                {"n": "Luz (EEQ)", "c": "servicios básicos", "i": ["luz", "eeq"]}, 
                {"n": "Agua", "c": "servicios básicos", "i": ["agua", "pisque"]}, 
                {"n": "Internet", "c": "servicios básicos", "i": ["internet", "fasttnet"]}, 
                {"n": "Asig. Laura", "c": "asignación Laura", "i": []}, 
                {"n": "Sueldo Julio", "c": "sueldo (incluye FR)", "i": []}, 
                {"n": "IESS", "c": "IESS", "i": []}, 
                {"n": "Préstamo IESS", "c": "Préstamo IESS", "i": []}
            ]
            for item in radar_items:
                st.markdown(f"✅ **{item['n']}**" if check_radar(item['c'], item['i']) else f"⚠️ **{item['n']}** (Pendiente)")
        
        st.markdown("---")
        col_chart1, col_chart2, col_chart3 = st.columns([2, 2, 1])
        with col_chart1:
            st.markdown("#### Flujo del Periodo Seleccionado")
            if not df_filtered.empty:
                df_flujo = df_filtered.groupby([df_filtered['Fecha'].dt.to_period('M'), 'Tipo'])['Monto'].sum().reset_index()
                df_flujo['Fecha'] = df_flujo['Fecha'].astype(str)
                st.plotly_chart(px.bar(df_flujo, x='Fecha', y='Monto', color='Tipo', barmode='group', color_discrete_map={'Ingreso':'#709b8b', 'Gasto':'#c9806b'}), use_container_width=True)
        
        with col_chart2:
            st.markdown("#### Distribución de Gastos")
            df_gastos = df_filtered[df_filtered['Tipo'] == 'Gasto']
            if not df_gastos.empty: 
                st.plotly_chart(px.pie(df_gastos, values='Monto', names='Categoría', hole=0.4), use_container_width=True)
            else: 
                st.info("No hay gastos registrados en este periodo con los filtros actuales.")
        
        with col_chart3:
            st.markdown("#### 💰 Provisiones")
            st.metric("Total Inmovilizado", f"${total_inmovilizado_global:,.2f}")
            st.dataframe(pd.DataFrame(datos_prov_global).style.format({'Acumulado': "${:,.2f}"}), hide_index=True)

        st.markdown("---")
        st.markdown("### 🕒 Últimos 5 Movimientos")
        df_ultimos = df[df['Categoría'] != 'comisión banco'].sort_values(by="Fecha", ascending=False).head(5).copy()
        df_ultimos['Fecha'] = df_ultimos['Fecha'].dt.strftime('%d/%m/%Y')
        st.dataframe(df_ultimos[['Fecha', 'Tipo', 'Categoría', 'Concepto', 'Monto']].style.format({'Monto': "${:,.2f}"}), hide_index=True, use_container_width=True)
    else: 
        st.warning("No se encontraron datos en la base principal. Por favor, asegúrate de haber subido el archivo `quinche_data.db` correcto.")

# --- TAB 2: VISTA DE BASES DE DATOS ---
with tab2:
    st.markdown("### 🗂️ Explorador de Datos (Solo Lectura)")
    st.write("Visualiza el histórico completo de las bases de datos. No es posible editar la información desde esta vista.")
    
    tabla_ver = st.selectbox("Selecciona la base de datos a explorar:", ["Movimientos Financieros", "Portafolio de Inversiones", "Cuentas por Cobrar"])
    
    if tabla_ver == "Movimientos Financieros" and not df.empty:
        df_show = df.sort_values(by="Fecha", ascending=False).copy()
        df_show['Fecha'] = df_show['Fecha'].dt.strftime('%d/%m/%Y')
        st.dataframe(df_show, use_container_width=True, hide_index=True)
    elif tabla_ver == "Portafolio de Inversiones" and not df_inv.empty:
        df_inv_show = df_inv.copy()
        df_inv_show['Fecha Inicio'] = df_inv_show['Fecha Inicio'].dt.strftime('%d/%m/%Y')
        st.dataframe(df_inv_show, use_container_width=True, hide_index=True)
    elif tabla_ver == "Cuentas por Cobrar" and not df_act.empty:
        df_act_show = df_act.copy()
        df_act_show['Fecha'] = df_act_show['Fecha'].dt.strftime('%d/%m/%Y')
        st.dataframe(df_act_show, use_container_width=True, hide_index=True)

# --- TAB 3: ASISTENTE AI ---
with tab3:
    col_ia1, col_ia2 = st.columns([4, 1])
    with col_ia1:
        st.markdown("### 🤖 Asistente Financiero AI (Groq + Llama 3.3)")
        st.write("Hazle preguntas a la inteligencia artificial sobre el estado financiero de El Quinche. Analizará todas las bases de datos al instante.")
    with col_ia2:
        if st.button("🔄 Borrar Memoria", use_container_width=True):
            st.session_state.messages_ai = []
            st.rerun()

    if "messages_ai" not in st.session_state:
        st.session_state.messages_ai = []

    # Mostrar historial
    for message in st.session_state.messages_ai:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Caja de chat
    if prompt := st.chat_input("Ej: ¿Cuánto he gastado en servicios básicos este año?"):
        st.session_state.messages_ai.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            try:
                with st.spinner('Analizando los datos...'):
                    # Preparación de datos (solo lo esencial para no exceder contexto de Groq)
                    if not df.empty:
                        df_ia = df[['Fecha', 'Tipo', 'Categoría', 'Monto', 'Concepto']].copy()
                        df_ia['Fecha'] = pd.to_datetime(df_ia['Fecha']).dt.strftime('%Y-%m-%d')
                        csv_master = df_ia.to_csv(index=False)
                    else:
                        csv_master = "No hay registros en la base de datos maestra."

                    csv_inv = df_inv[['Fecha Inicio', 'Entidad', 'Monto', 'Estado']].to_csv(index=False) if not df_inv.empty else "No hay inversiones registradas."
                    csv_prov = pd.DataFrame(datos_prov_global).to_csv(index=False) if datos_prov_global else "No hay provisiones registradas."
                    saldo_str = f"SALDO BANCARIO ACTUAL CALCULADO: ${saldo_real_actual:.2f}\n" if 'saldo_real_actual' in locals() else ""

                    client = Groq(api_key=GROQ_API_KEY)
                    system_prompt = f"""
                    Eres el analista de datos y asistente financiero del dashboard 'El Quinche'. 
                    Tu misión es responder las dudas del usuario basándote ESTRICTAMENTE en los datos CSV que se te proporcionan a continuación.
                    
                    DATOS DE MOVIMIENTOS (Ingresos y Gastos):
                    {csv_master}
                    
                    DATOS DE INVERSIONES:
                    {csv_inv}
                    
                    FONDOS DE PROVISIONES:
                    {csv_prov}
                    
                    {saldo_str}
                    
                    REGLAS IMPORTANTES Y PROHIBICIONES ABSOLUTAS:
                    1. TIENES PROHIBIDO TAJANTEMENTE hablar, discutir o responder sobre CUALQUIER tema que no esté estrictamente relacionado con este dashboard financiero, los datos proporcionados, finanzas o contabilidad del proyecto 'El Quinche'. Si el usuario pregunta sobre programación, historia, recetas, chistes o cualquier otra cosa fuera de contexto, debes negarte educada pero firmemente.
                    2. NO le digas al usuario cómo usar el dashboard. Lee tú mismo los datos y dale la respuesta final.
                    3. Si te preguntan por un mes o categoría, filtra mentalmente el archivo CSV, suma los montos y entrégale el valor exacto.
                    4. Sé amigable, directo y claro. Usa el símbolo $ para los montos.
                    5. Responde siempre en español.
                    """

                    messages_to_send = [{"role": "system", "content": system_prompt}] + st.session_state.messages_ai

                    completion = client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=messages_to_send,
                        temperature=0.1, # Temperatura baja para que sea preciso con los números
                        max_tokens=600,
                    )

                    response = completion.choices[0].message.content
                    st.markdown(response)
                    st.session_state.messages_ai.append({"role": "assistant", "content": response})

            except Exception as e:
                st.error(f"Hubo un problema procesando tu pregunta con la IA: {e}")