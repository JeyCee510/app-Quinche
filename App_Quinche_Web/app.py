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
        return pd.DataFrame()
 
df = cargar_tabla("master")
df_inv = cargar_tabla("inversiones")
df_act = cargar_tabla("activos")
df_prov_hist = cargar_tabla("prov_hist")
 
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
st.set_page_config(
    page_title="Dashboard Quinche", 
    layout="wide", 
    initial_sidebar_state="expanded" 
)
 
st.markdown("""
<style>
    [data-testid="stMetric"] { 
        padding: 15px 20px; 
        border-radius: 12px; 
        border: 1px solid rgba(128, 128, 128, 0.2); 
        background-color: var(--secondary-background-color); 
    }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { border-radius: 8px 8px 0 0; }
</style>
""", unsafe_allow_html=True)
 
st.title("📊 Panel Financiero - El Quinche (Visor)")
st.info("🔒 Esta es una versión de acceso público y solo lectura. Los datos están protegidos.")
 
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
 
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 Dashboard Principal", "🗂️ Detalle de Movimientos", "💰 Provisiones", "🤖 Asistente IA", "📇 Info Esencial"])
 
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
            def check_radar(cat_exacta, inc):
                mask = gastos_mes_actual['Categoría'] == cat_exacta
                if mask.sum() == 0: return False
                for _, r in gastos_mes_actual[mask].iterrows():
                    txt = str(r['Concepto']).lower() + " " + str(r['Detalle']).lower()
                    if not inc or any(k.lower() in txt for k in inc): return True
                return False
            
            radar_items = [
                {"n": "Luz (EEQ)",      "c": "servicios básicos",   "i": ["luz", "eeq"],            "dia": 16},
                {"n": "Agua (EPMAPS)",  "c": "servicios básicos",   "i": ["agua", "epmaps"],        "dia": 24},
                {"n": "Internet",       "c": "servicios básicos",   "i": ["internet", "fasttnet"],  "dia": 2},
                {"n": "Asig. Laura",    "c": "asignación Laura",    "i": [],                        "dia": 2},
                {"n": "Sueldo Julio",   "c": "sueldo (incluye FR)", "i": [],                        "dia": 2},
                {"n": "IESS",           "c": "IESS",                "i": [],                        "dia": 4},
                {"n": "Préstamo IESS",  "c": "Préstamo IESS",       "i": [],                        "dia": 1}
            ]
            hoy_dia = hoy.day
            # Clasificación: 0=atrasado, 1=por vencer pronto (≤5 días), 2=pendiente, 3=pagado
            radar_eval = []
            for item in radar_items:
                pagado = check_radar(item['c'], item['i'])
                d = item['dia']
                if pagado:
                    estado, prio = "pagado", 3
                elif hoy_dia > d:
                    estado, prio = "atrasado", 0
                elif (d - hoy_dia) <= 5:
                    estado, prio = "vence_pronto", 1
                else:
                    estado, prio = "pendiente", 2
                radar_eval.append({"item": item, "estado": estado, "prio": prio, "dia": d})

            radar_eval.sort(key=lambda x: (x["prio"], x["dia"]))
            for ev in radar_eval:
                nombre = ev["item"]["n"]
                d = ev["dia"]
                if ev["estado"] == "atrasado":
                    st.markdown(f":red[🔴 **{nombre}** · atrasado desde día {d}]")
                elif ev["estado"] == "vence_pronto":
                    st.markdown(f":orange[🟡 **{nombre}** · vence día {d} (próximo)]")
                elif ev["estado"] == "pendiente":
                    st.markdown(f":blue[🔵 **{nombre}** · vence día {d}]")
                else:
                    st.markdown(f":gray[✅ {nombre} · día {d}]")
        
        st.markdown("---")
        col_chart1, col_chart2, col_chart3 = st.columns([2, 2, 1])
        with col_chart1:
            st.markdown("#### Flujo del Periodo Seleccionado")
            if not df_filtered.empty:
                df_flujo = df_filtered.groupby([df_filtered['Fecha'].dt.to_period('M'), 'Tipo'])['Monto'].sum().reset_index()
                df_flujo['Fecha'] = df_flujo['Fecha'].astype(str)
                st.plotly_chart(px.bar(df_flujo, x='Fecha', y='Monto', color='Tipo', barmode='group', color_discrete_map={'Ingreso':'#709b8b', 'Gasto':'#c9806b'}), width="stretch")
        
        with col_chart2:
            st.markdown("#### Distribución de Gastos")
            df_gastos = df_filtered[df_filtered['Tipo'] == 'Gasto']
            if not df_gastos.empty: 
                st.plotly_chart(px.pie(df_gastos, values='Monto', names='Categoría', hole=0.4), width="stretch")
            else: 
                st.info("No hay gastos registrados en este periodo.")
        
        with col_chart3:
            st.markdown("#### 💰 Provisiones")
            _meses_es_dash = {1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
                              7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"}
            _hoy_dash = datetime.now()
            _primer_dia_mes_act = datetime(_hoy_dash.year, _hoy_dash.month, 1)
            _ultimo_dia_mes_previo = _primer_dia_mes_act - timedelta(days=1)
            _inicio_mes_previo_dash = _ultimo_dia_mes_previo.replace(day=1)
            _fecha_corte_str = f"{_ultimo_dia_mes_previo.day} de {_meses_es_dash[_ultimo_dia_mes_previo.month]} {_ultimo_dia_mes_previo.year}"
            st.caption(f"📅 Corte al {_fecha_corte_str}")
            if not df_prov_hist.empty:
                _f_ultimo_reg = pd.to_datetime(df_prov_hist['Fecha']).max()
                if _f_ultimo_reg.to_pydatetime() < _inicio_mes_previo_dash:
                    _ult_reg_str = f"{_f_ultimo_reg.day} de {_meses_es_dash[_f_ultimo_reg.month]} {_f_ultimo_reg.year}"
                    st.caption(f"⚠️ Aún no se aplican las cuotas del mes previo (último registro: {_ult_reg_str})")
            else:
                st.caption("⚠️ Sin cierres registrados aún")
            st.metric("Total Inmovilizado", f"${total_inmovilizado_global:,.2f}")
            st.dataframe(pd.DataFrame(datos_prov_global).style.format({'Acumulado': "${:,.2f}"}), hide_index=True, width="stretch")
 
        st.markdown("---")
        st.markdown("### 📈 Evolución de Gastos")
        st.caption("Análisis histórico independiente de los filtros del sidebar.")
 
        df_gastos_all = df[df['Tipo'] == 'Gasto'].copy()
 
        if df_gastos_all.empty:
            st.info("No hay gastos registrados aún.")
        else:
            df_gastos_all['MesPeriodo'] = df_gastos_all['Fecha'].dt.to_period('M')
            meses_disponibles = sorted(df_gastos_all['MesPeriodo'].dropna().unique())
            etiquetas_meses = [m.strftime('%b %Y') for m in meses_disponibles]
            mapa_etiqueta = dict(zip(etiquetas_meses, meses_disponibles))
 
            modo_evol = st.radio("Agrupar por:",
                ["Categoría", "Concepto/Tag"],
                horizontal=True, key='evolucion_modo')
 
            col_ev1, col_ev2, col_ev3 = st.columns([2, 1, 1])
            with col_ev1:
                if modo_evol == "Categoría":
                    seleccion = st.multiselect("Categorías a graficar:",
                        options=CATEGORIAS_EXACTAS, default=[], key='evolucion_cats')
                else:
                    tags_input = st.text_input(
                        "Tags (separados por coma) — busca en Concepto y Detalle:",
                        value="", placeholder="ej: EPMAPS, EEQ, internet, Laura",
                        key='evolucion_tags')
                    seleccion = [t.strip() for t in tags_input.split(",") if t.strip()]
            with col_ev2:
                mes_desde = st.selectbox("Desde:", etiquetas_meses, index=0, key='evolucion_desde')
            with col_ev3:
                mes_hasta = st.selectbox("Hasta:", etiquetas_meses,
                    index=len(etiquetas_meses)-1, key='evolucion_hasta')
 
            col_ev4, col_ev5 = st.columns([2, 1])
            with col_ev4:
                tipo_grafico = st.radio("Tipo de gráfico:",
                    ["Líneas", "Barras agrupadas", "Barras apiladas"],
                    horizontal=True, key='evolucion_tipo')
            with col_ev5:
                mostrar_total = st.checkbox("Mostrar total agregado",
                    value=False, key='evolucion_total')
 
            if not seleccion:
                if modo_evol == "Categoría":
                    st.info("Selecciona una o más categorías para ver la evolución.")
                else:
                    st.info("Escribe uno o más tags (separados por coma) para ver la evolución.")
            else:
                p_desde, p_hasta = mapa_etiqueta[mes_desde], mapa_etiqueta[mes_hasta]
                if p_desde > p_hasta:
                    p_desde, p_hasta = p_hasta, p_desde
 
                df_rango = df_gastos_all[
                    (df_gastos_all['MesPeriodo'] >= p_desde) &
                    (df_gastos_all['MesPeriodo'] <= p_hasta)
                ].copy()
 
                if modo_evol == "Categoría":
                    df_ev = df_rango[df_rango['Categoría'].isin(seleccion)].copy()
                    df_ev['Serie'] = df_ev['Categoría']
                else:
                    partes = []
                    for tag in seleccion:
                        tag_low = tag.lower()
                        mask = (df_rango['Concepto'].fillna('').str.lower().str.contains(tag_low, regex=False) |
                                df_rango['Detalle'].fillna('').str.lower().str.contains(tag_low, regex=False))
                        sub = df_rango[mask].copy()
                        sub['Serie'] = tag
                        partes.append(sub)
                    df_ev = pd.concat(partes, ignore_index=True) if partes else df_rango.iloc[0:0].assign(Serie='')
 
                if df_ev.empty:
                    st.warning("No hay gastos que coincidan en ese rango.")
                else:
                    todos_meses = pd.period_range(p_desde, p_hasta, freq='M')
                    grilla = pd.MultiIndex.from_product([todos_meses, seleccion], names=['MesPeriodo', 'Serie'])
                    df_agg = (df_ev.groupby(['MesPeriodo', 'Serie'])['Monto'].sum()
                              .reindex(grilla, fill_value=0).reset_index())
                    df_agg['Mes'] = df_agg['MesPeriodo'].apply(lambda p: p.strftime('%b %Y'))
                    orden = [p.strftime('%b %Y') for p in todos_meses]
                    legend_title = "Categoría" if modo_evol == "Categoría" else "Tag"
 
                    if tipo_grafico == "Líneas":
                        fig_ev = px.line(df_agg, x='Mes', y='Monto', color='Serie',
                            markers=True, category_orders={'Mes': orden})
                    elif tipo_grafico == "Barras agrupadas":
                        fig_ev = px.bar(df_agg, x='Mes', y='Monto', color='Serie',
                            barmode='group', category_orders={'Mes': orden})
                    else:
                        fig_ev = px.bar(df_agg, x='Mes', y='Monto', color='Serie',
                            barmode='stack', category_orders={'Mes': orden})
 
                    if mostrar_total:
                        df_tot = df_agg.groupby('Mes', as_index=False)['Monto'].sum()
                        df_tot['Mes'] = pd.Categorical(df_tot['Mes'], categories=orden, ordered=True)
                        df_tot = df_tot.sort_values('Mes')
                        fig_ev.add_scatter(x=df_tot['Mes'], y=df_tot['Monto'],
                            mode='lines+markers', name='Total',
                            line=dict(color='black', dash='dash'))
 
                    fig_ev.update_layout(yaxis_tickformat=',.0f',
                        xaxis_title="Mes", yaxis_title="Monto ($)",
                        legend_title_text=legend_title)
                    st.plotly_chart(fig_ev, width="stretch")
 
        st.markdown("---")
        st.markdown("### 🕒 Últimos 5 Movimientos")
        df_ultimos = df[df['Categoría'] != 'comisión banco'].sort_values(by="Fecha", ascending=False).head(5).copy()
        df_ultimos['Fecha'] = df_ultimos['Fecha'].dt.strftime('%d/%m/%Y')
        st.dataframe(df_ultimos[['Fecha', 'Tipo', 'Categoría', 'Concepto', 'Monto']].style.format({'Monto': "${:,.2f}"}), hide_index=True, width="stretch")
    else: 
        st.warning("No se encontraron datos.")
 
# --- TAB 2: VISTA DE BASES DE DATOS ---
with tab2:
    st.markdown("### 🗂️ Explorador de Datos (Solo Lectura)")
    tabla_ver = st.selectbox("Selecciona la base de datos a explorar:", ["Movimientos Financieros", "Portafolio de Inversiones", "Cuentas por Cobrar"])
    
    if tabla_ver == "Movimientos Financieros" and not df.empty:
        df_show = df.sort_values(by="Fecha", ascending=False).copy()
        df_show['Fecha'] = df_show['Fecha'].dt.strftime('%d/%m/%Y')
        st.dataframe(df_show, width="stretch", hide_index=True)
    elif tabla_ver == "Portafolio de Inversiones" and not df_inv.empty:
        df_inv_show = df_inv.copy()
        df_inv_show['Fecha Inicio'] = df_inv_show['Fecha Inicio'].dt.strftime('%d/%m/%Y')
        st.dataframe(df_inv_show, width="stretch", hide_index=True)
    elif tabla_ver == "Cuentas por Cobrar" and not df_act.empty:
        df_act_show = df_act.copy()
        df_act_show['Fecha'] = df_act_show['Fecha'].dt.strftime('%d/%m/%Y')
        st.dataframe(df_act_show, width="stretch", hide_index=True)
 
# --- TAB 3: PROVISIONES (SOLO LECTURA) ---
with tab3:
    st.markdown("### 💰 Fondo de Provisiones")
    _meses_es_p = {1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
                   7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"}
    _hoy_p = datetime.now()
    _primer_dia_p = datetime(_hoy_p.year, _hoy_p.month, 1)
    _ultimo_dia_mes_previo_p = _primer_dia_p - timedelta(days=1)
    _inicio_mes_previo_p = _ultimo_dia_mes_previo_p.replace(day=1)
    _fecha_corte_str_p = f"{_ultimo_dia_mes_previo_p.day} de {_meses_es_p[_ultimo_dia_mes_previo_p.month]} {_ultimo_dia_mes_previo_p.year}"
    st.caption(f"📅 Corte al {_fecha_corte_str_p}")
    if not df_prov_hist.empty:
        _f_ultimo_reg_p = pd.to_datetime(df_prov_hist['Fecha']).max()
        if _f_ultimo_reg_p.to_pydatetime() < _inicio_mes_previo_p:
            _ult_reg_str_p = f"{_f_ultimo_reg_p.day} de {_meses_es_p[_f_ultimo_reg_p.month]} {_f_ultimo_reg_p.year}"
            st.caption(f"⚠️ Aún no se aplican las cuotas del mes previo (último registro: {_ult_reg_str_p})")
    else:
        st.caption("⚠️ Sin cierres registrados aún")

    st.markdown("#### Estado actual del fondo")
    datos_prov_full_v = [{"Rubro": k, "Detalle / Vencimiento": v.get("nota", ""), "Cuota Mensual": float(v.get("mensual", 0.0)), "Acumulado Actual": float(v["acumulado"])} for k, v in config["provisiones"].items()]
    st.dataframe(pd.DataFrame(datos_prov_full_v).style.format({'Cuota Mensual': "${:,.2f}", 'Acumulado Actual': "${:,.2f}"}), hide_index=True, width="stretch")
    st.markdown(f"### Total Fondo Inmovilizado: **${total_inmovilizado_global:,.2f}**")

    st.markdown("---")
    st.markdown("#### 📈 Evolución mensual del Fondo")
    st.caption("Para cada mes y rubro se toma el último acumulado registrado. Si un rubro no tuvo movimiento ese mes, se arrastra el saldo del mes anterior.")
    if df_prov_hist.empty:
        st.info("Aún no hay registros en el historial de provisiones.")
    else:
        df_hist_evol = df_prov_hist.copy()
        df_hist_evol['Fecha'] = pd.to_datetime(df_hist_evol['Fecha'], errors='coerce')
        df_hist_evol = df_hist_evol.dropna(subset=['Fecha'])
        df_hist_evol['Mes'] = df_hist_evol['Fecha'].dt.to_period('M')
        df_hist_evol = df_hist_evol.sort_values('Fecha')
        df_ultimo_mes = df_hist_evol.groupby(['Mes', 'Rubro'], as_index=False).last()
        pivote_evol = df_ultimo_mes.pivot(index='Mes', columns='Rubro', values='Acumulado').sort_index()
        pivote_evol = pivote_evol.ffill().fillna(0.0)
        pivote_evol['TOTAL INMOVILIZADO'] = pivote_evol.sum(axis=1)
        pivote_evol = pivote_evol.sort_index(ascending=False)
        pivote_evol.index = pivote_evol.index.strftime('%b %Y')
        pivote_evol.index.name = 'Mes'
        st.dataframe(pivote_evol.style.format("${:,.2f}"), width="stretch")

        with st.expander("Ver historial crudo (todas las filas)"):
            df_crudo = df_prov_hist.copy()
            df_crudo['Fecha'] = pd.to_datetime(df_crudo['Fecha']).dt.strftime('%Y-%m-%d')
            st.dataframe(df_crudo.sort_values(by="Fecha", ascending=False), hide_index=True, width="stretch")

# --- TAB 4: ASISTENTE AI ---
with tab4:
    col_ia1, col_ia2 = st.columns([4, 1])
    with col_ia1:
        st.markdown("### 🤖 Asistente Financiero AI")
        st.write("Analizo las bases de datos de El Quinche para responder tus dudas.")
    with col_ia2:
        if st.button("🧼 Limpiar pantalla", width="stretch"):
            st.session_state.messages_ai = []
            st.rerun()
 
    if "messages_ai" not in st.session_state: st.session_state.messages_ai = []
 
    for message in st.session_state.messages_ai:
        with st.chat_message(message["role"]): st.markdown(message["content"])
 
    if prompt := st.chat_input("Ej: ¿Cuánto he gastado en servicios básicos este año?"):
        st.session_state.messages_ai.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)
 
        with st.chat_message("assistant"):
            try:
                with st.spinner('Analizando los datos...'): 
                    if not df.empty:
                        df_ia = df[['Fecha', 'Tipo', 'Categoría', 'Monto', 'Concepto']].copy()
                        df_ia['Fecha'] = pd.to_datetime(df_ia['Fecha']).dt.strftime('%Y-%m-%d')
                        csv_master = df_ia.to_csv(index=False)
                    else: csv_master = "Sin registros."
 
                    csv_inv = df_inv[['Fecha Inicio', 'Entidad', 'Monto', 'Estado']].to_csv(index=False) if not df_inv.empty else "Sin inversiones."
                    csv_prov = pd.DataFrame(datos_prov_global).to_csv(index=False) if datos_prov_global else "Sin provisiones."
                    saldo_str = f"SALDO BANCARIO ACTUAL: ${saldo_real_actual:.2f}\n" if 'saldo_real_actual' in locals() else ""
 
                    client = Groq(api_key=GROQ_API_KEY)
                    system_prompt = f"Eres el analista financiero de 'El Quinche'. Responde usando estos datos:\n{csv_master}\n{csv_inv}\n{csv_prov}\n{saldo_str}\nReglas: Solo temas financieros de este proyecto. Sé directo y usa $."
 
                    messages_to_send = [{"role": "system", "content": system_prompt}] + st.session_state.messages_ai
                    completion = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=messages_to_send, temperature=0.1, max_tokens=600)
 
                    response = completion.choices[0].message.content
                    st.markdown(response)
                    st.session_state.messages_ai.append({"role": "assistant", "content": response})
            except Exception as e: st.error(f"Error: {e}")

# --- TAB 5: INFO ESENCIAL (SOLO LECTURA) ---
with tab5:
    st.markdown("### 📇 Info Esencial")
    st.caption("Números, cédulas y contactos clave para gestión y pagos. Pasa el cursor sobre cada número para copiarlo.")

    col_ie_a, col_ie_b = st.columns(2)

    with col_ie_a:
        st.markdown("#### 🔌 Suministros / servicios públicos")
        st.markdown("**EEQ** — Empresa Eléctrica Quito")
        st.code("201003213893", language="")
        st.markdown("**EPMAPS** — Agua Quito")
        st.code("9930992954", language="")
        st.markdown("**FASTTNET** — Internet · contrato a nombre de Martín Lira")
        st.code("+593 99 001 6984", language="")
        st.caption("Vía WhatsApp")

        st.markdown("---")
        st.markdown("#### 🏡 Predios")
        st.markdown("**Sausalito** — Número de predio")
        st.code("5604289", language="")

        st.markdown("---")
        st.markdown("#### 💼 Pagos institucionales")
        st.markdown("**IESS Julio en Produ**")
        st.markdown("RUC:")
        st.code("1702788603001", language="")
        st.markdown("Sucursal:")
        st.code("0001", language="")

    with col_ie_b:
        st.markdown("#### 🪪 Cédulas")
        st.markdown("**Julio Imbacuán**")
        st.code("1761026432", language="")
        st.markdown("**Tita Marujita**")
        st.code("1702896380", language="")

        st.markdown("---")
        st.markdown("#### 📞 Contactos")
        st.markdown("**Sandra** — Agua Pisque")
        st.code("0994984063", language="")
        st.markdown("**Florícola** — *Por completar*")
        st.caption("Nombre, teléfono y correo pendientes de definir.")
 
