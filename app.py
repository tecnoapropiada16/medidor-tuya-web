import streamlit as st
import tinytuya
import pandas as pd
import numpy as np
import base64
import time
import os
import json
import threading
from datetime import datetime, date
import io
import plotly.graph_objects as go
import plotly.express as px
from streamlit_autorefresh import st_autorefresh

# ==================================================
# CONFIGURACIÓN TUYA CLOUD & ARCHIVOS PERSISTENTES
# ==================================================
CONFIG = {
    "API_KEY": "9gpha3dftmnmgy3x4cwg",
    "API_SECRET": "99b91b2ddb4540d7ae9a1be09998e19e",
    "API_REGION": "us",
    "PHASE_CODES": ["phase_a", "phase_b", "phase_c"]
}

MEDIDORES = {
    "Medidor Nuevo (Julbrainer)": "eb57cc368c5cc5081cfoqw",
    "Medidor Viejo (METER Aprotec)": "eb839fc51ff84a3d4bof4v"
}

FORWARD_SCALE_FACTOR = 10.0
REVERSE_SCALE_FACTOR = 10.0

CONFIG_FILE = "config_persistent.json"
DATA_FILE = "datos_monitoreo.json"

st.set_page_config(
    page_title="Datos Operativos - Medidor Tuya Cloud 24/7",
    page_icon="⚡",
    layout="wide"
)

# Estilos CSS personalizados
st.markdown("""
<style>
    .main-header {
        font-size: 24px;
        font-weight: 700;
        color: #2c3e50;
        margin-bottom: 15px;
    }
    .energy-card {
        background-color: #ffffff;
        border-radius: 12px;
        padding: 16px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        border: 1px solid #eef2f5;
        margin-bottom: 12px;
    }
    .metric-value {
        font-size: 22px;
        font-weight: bold;
        color: #1e293b;
    }
    .metric-label {
        font-size: 13px;
        color: #64748b;
        margin-top: 2px;
    }
    .role-badge-guest {
        background-color: #e2e8f0;
        color: #475569;
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
    }
    .role-badge-admin {
        background-color: #dcfce7;
        color: #166534;
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# Helper functions
def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

def decode_phase_data(base64_string):
    try:
        decoded_bytes = base64.b64decode(base64_string)
        hex_string = decoded_bytes.hex()
        if len(hex_string) != 16:
            return {"error": "Longitud inválida"}
        voltage = int(hex_string[0:4], 16) * 0.1
        current = int(hex_string[4:10], 16) * 0.001
        power = int(hex_string[10:16], 16)
        return {"Voltaje": voltage, "Corriente": current, "Potencia": power}
    except Exception as e:
        return {"error": f"Decodificación fallida: {e}"}

def procesar_datos_crudos(datos_crudos):
    datos_procesados = {}
    if isinstance(datos_crudos, list):
        for item in datos_crudos:
            code = item.get('code', '')
            value = item.get('value', '')
            datos_procesados[code] = value
    return datos_procesados

# FUNCIONES DE PERSISTENCIA EN DISCO (JSON)
def cargar_config_persistente():
    default_config = {
        "admin_password": "admin",
        "monitoreo_activo": False,
        "intervalo_seg": 60,
        "medidor_sel": "Medidor Nuevo (Julbrainer)",
        "tarifa_cop": 850.0
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_config.update(saved)
        except Exception:
            pass
    return default_config

def guardar_config_persistente(config_dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, indent=2)
    except Exception as e:
        print("Error guardando config:", e)

def cargar_datos_persistentes():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def guardar_datos_persistentes(datos):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2)
    except Exception as e:
        print("Error guardando datos:", e)

# HILO DE MONITOREO DE FONDO 24/7 (Corre independientemente del navegador)
if "thread_started" not in globals():
    globals()["thread_started"] = False

def background_tuya_worker():
    print("[HILO FONDO] Iniciado servicio de monitoreo 24/7...")
    while True:
        try:
            cfg = cargar_config_persistente()
            if cfg.get("monitoreo_activo", False):
                intervalo = cfg.get("intervalo_seg", 60)
                medidor_nombre = cfg.get("medidor_sel", "Medidor Nuevo (Julbrainer)")
                device_id = MEDIDORES.get(medidor_nombre, list(MEDIDORES.values())[0])

                cloud = tinytuya.Cloud(
                    apiRegion=CONFIG["API_REGION"],
                    apiKey=CONFIG["API_KEY"],
                    apiSecret=CONFIG["API_SECRET"],
                    apiDeviceID=device_id
                )
                raw = cloud.getstatus(device_id)
                if raw and raw.get("success", False):
                    datos_raw = procesar_datos_crudos(raw.get("result", []))
                    forward_wh = safe_float(datos_raw.get("forward_energy_total", 0)) * FORWARD_SCALE_FACTOR
                    reverse_wh = safe_float(datos_raw.get("reverse_energy_total", 0)) * REVERSE_SCALE_FACTOR

                    phase_values = {}
                    for idx, code in enumerate(CONFIG["PHASE_CODES"], start=1):
                        raw_phase = datos_raw.get(code)
                        if raw_phase:
                            decoded = decode_phase_data(raw_phase)
                            if "error" not in decoded:
                                phase_values[f"V{chr(64+idx)}"] = round(decoded["Voltaje"], 2)
                                phase_values[f"I{chr(64+idx)}"] = round(decoded["Corriente"], 3)
                                phase_values[f"P{chr(64+idx)}"] = round(decoded["Potencia"], 1)
                            else:
                                phase_values[f"V{chr(64+idx)}"] = 0.0
                                phase_values[f"I{chr(64+idx)}"] = 0.0
                                phase_values[f"P{chr(64+idx)}"] = 0.0
                        else:
                            phase_values[f"V{chr(64+idx)}"] = 0.0
                            phase_values[f"I{chr(64+idx)}"] = 0.0
                            phase_values[f"P{chr(64+idx)}"] = 0.0

                    datos_existentes = cargar_datos_persistentes()
                    ultima_forward = None
                    ultima_reverse = None
                    if datos_existentes:
                        ultima_forward = datos_existentes[-1].get("energia_consumida_wh")
                        ultima_reverse = datos_existentes[-1].get("energia_inyectada_wh")

                    consumo_intervalo = 0.0
                    exportado_intervalo = 0.0
                    if ultima_forward is not None:
                        consumo_intervalo = max(0.0, forward_wh - ultima_forward)
                    if ultima_reverse is not None:
                        exportado_intervalo = max(0.0, reverse_wh - ultima_reverse)

                    ahora_dt = datetime.now()
                    ts_str = ahora_dt.strftime("%Y-%m-%d %H:%M:%S")
                    total_power = phase_values.get("PA", 0.0) + phase_values.get("PB", 0.0) + phase_values.get("PC", 0.0)

                    nuevo_registro = {
                        "timestamp": ts_str,
                        "fecha": ahora_dt.strftime("%Y-%m-%d"),
                        "hora": ahora_dt.strftime("%H:%M:%S"),
                        "mes": ahora_dt.strftime("%Y-%m"),
                        "anio": ahora_dt.strftime("%Y"),
                        "energia_consumida_wh": round(forward_wh, 4),
                        "energia_inyectada_wh": round(reverse_wh, 4),
                        "consumo_intervalo_wh": round(consumo_intervalo, 4),
                        "exportado_intervalo_wh": round(exportado_intervalo, 4),
                        "potencia_total_w": round(total_power, 1),
                        "Va": phase_values.get("VA", phase_values.get("Va", 0.0)),
                        "Ia": phase_values.get("IA", phase_values.get("Ia", 0.0)),
                        "Pa": phase_values.get("PA", phase_values.get("Pa", 0.0)),
                        "Vb": phase_values.get("VB", phase_values.get("Vb", 0.0)),
                        "Ib": phase_values.get("IB", phase_values.get("Ib", 0.0)),
                        "Pb": phase_values.get("PB", phase_values.get("Pb", 0.0)),
                        "Vc": phase_values.get("VC", phase_values.get("Vc", 0.0)),
                        "Ic": phase_values.get("IC", phase_values.get("Ic", 0.0)),
                        "Pc": phase_values.get("PC", phase_values.get("Pc", 0.0))
                    }

                    datos_existentes.append(nuevo_registro)
                    guardar_datos_persistentes(datos_existentes)
                    print(f"[HILO FONDO] Registro guardado #{len(datos_existentes)}: {ts_str}")

                time.sleep(max(5, intervalo))
            else:
                time.sleep(2)
        except Exception as e:
            print("[HILO FONDO ERROR]", e)
            time.sleep(5)

if not globals()["thread_started"]:
    globals()["thread_started"] = True
    t = threading.Thread(target=background_tuya_worker, daemon=True)
    t.start()

# Cargar configuración global persistente
config_app = cargar_config_persistente()

# Inicializar sesión
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

# --- SIDEBAR (LOGIN & ADMIN CONTROLS) ---
st.sidebar.title("🔐 Acceso y Roles")

if not st.session_state.is_admin:
    st.sidebar.markdown("<span class='role-badge-guest'>👁️ Modo Invitado (Solo Lectura)</span>", unsafe_allow_html=True)
    st.sidebar.markdown("---")
    st.sidebar.subheader("Acceso Administrador")
    pass_input = st.sidebar.text_input("Contraseña:", type="password", key="pwd_input")
    if st.sidebar.button("🔓 Iniciar Sesión Admin"):
        if pass_input == config_app["admin_password"]:
            st.session_state.is_admin = True
            st.sidebar.success("¡Autenticado como Administrador!")
            st.rerun()
        else:
            st.sidebar.error("Contraseña incorrecta")
else:
    st.sidebar.markdown("<span class='role-badge-admin'>⚡ Modo Administrador Activo</span>", unsafe_allow_html=True)
    
    with st.sidebar.expander("🔑 Cambiar Contraseña"):
        pwd_actual = st.text_input("Contraseña Actual", type="password", key="pwd_actual")
        pwd_nueva = st.text_input("Nueva Contraseña", type="password", key="pwd_nueva")
        pwd_confirm = st.text_input("Confirmar Nueva Contraseña", type="password", key="pwd_confirm")
        
        if st.button("💾 Guardar Nueva Contraseña"):
            if pwd_actual != config_app["admin_password"]:
                st.error("La contraseña actual es incorrecta.")
            elif not pwd_nueva:
                st.error("La nueva contraseña no puede estar vacía.")
            elif pwd_nueva != pwd_confirm:
                st.error("Las nuevas contraseñas no coinciden.")
            else:
                config_app["admin_password"] = pwd_nueva
                guardar_config_persistente(config_app)
                st.success("¡Contraseña guardada permanentemente!")
                st.rerun()

    if st.sidebar.button("🔒 Cerrar Sesión Admin"):
        st.session_state.is_admin = False
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Parámetros de Monitoreo")

medidor_index = list(MEDIDORES.keys()).index(config_app.get("medidor_sel", list(MEDIDORES.keys())[0])) if config_app.get("medidor_sel") in MEDIDORES else 0
medidor_sel = st.sidebar.selectbox(
    "Seleccionar Medidor:",
    list(MEDIDORES.keys()),
    index=medidor_index,
    disabled=not st.session_state.is_admin
)
if medidor_sel != config_app.get("medidor_sel") and st.session_state.is_admin:
    config_app["medidor_sel"] = medidor_sel
    guardar_config_persistente(config_app)

intervalo_opciones = {"5s": 5, "15s": 15, "30s": 30, "60s (1 min)": 60, "5 min": 300, "15 min": 900}
inv_map = {v: k for k, v in intervalo_opciones.items()}
inv_nombre_actual = inv_map.get(config_app.get("intervalo_seg", 60), "60s (1 min)")
inv_index = list(intervalo_opciones.keys()).index(inv_nombre_actual)

intervalo_nombre = st.sidebar.selectbox(
    "Intervalo de Lectura:",
    list(intervalo_opciones.keys()),
    index=inv_index,
    disabled=not st.session_state.is_admin
)
intervalo_seg = intervalo_opciones[intervalo_nombre]
if intervalo_seg != config_app.get("intervalo_seg") and st.session_state.is_admin:
    config_app["intervalo_seg"] = intervalo_seg
    guardar_config_persistente(config_app)

if st.session_state.is_admin:
    nueva_tarifa = st.sidebar.number_input(
        "Tarifa COP/kWh:",
        value=float(config_app.get("tarifa_cop", 850.0)),
        step=50.0
    )
    if nueva_tarifa != config_app.get("tarifa_cop"):
        config_app["tarifa_cop"] = nueva_tarifa
        guardar_config_persistente(config_app)

col_btn1, col_btn2 = st.sidebar.columns(2)
with col_btn1:
    if not config_app.get("monitoreo_activo", False):
        if st.sidebar.button("▶️ Iniciar Monitoreo", use_container_width=True, type="primary", disabled=not st.session_state.is_admin):
            config_app["monitoreo_activo"] = True
            guardar_config_persistente(config_app)
            st.rerun()
    else:
        if st.sidebar.button("⏹️ Detener Monitoreo", use_container_width=True, type="secondary", disabled=not st.session_state.is_admin):
            config_app["monitoreo_activo"] = False
            guardar_config_persistente(config_app)
            st.rerun()

with col_btn2:
    if st.sidebar.button("🗑️ Limpiar Datos", use_container_width=True, disabled=not st.session_state.is_admin):
        guardar_datos_persistentes([])
        st.rerun()

if config_app.get("monitoreo_activo", False):
    st.sidebar.success(f"🟢 Activo 24/7 ({intervalo_seg}s)")
    st_autorefresh(interval=intervalo_seg * 1000, key="tuya_autorefresh")
else:
    st.sidebar.info("⏸️ En pausa")

# --- CARGA DE DATOS DESDE DISCO ---
raw_records = cargar_datos_persistentes()
df_all = pd.DataFrame(raw_records) if len(raw_records) > 0 else pd.DataFrame()
registro_actual = raw_records[-1] if len(raw_records) > 0 else None

# --- ENCABEZADO Y CONTROLES SUPERIORES (DÍA / MES / AÑO / TOTAL) ---
col_head1, col_head2 = st.columns([2, 3])

with col_head1:
    st.markdown("<div class='main-header'>Datos Operativos</div>", unsafe_allow_html=True)

with col_head2:
    tab_vista = st.radio(
        "",
        ["Día", "Mes", "Año", "Total"],
        horizontal=True,
        key="selected_view_mode"
    )

st.markdown("---")

# Variables para las métricas
total_consumo_kwh = 0.0
total_exportado_kwh = 0.0
total_generacion_kwh = 0.0
pct_consumo = 50.0
pct_ared = 50.0
ganancia_cop = 0.0
horas_plena_carga = 0.0

if not df_all.empty:
    total_consumo_kwh = df_all['consumo_intervalo_wh'].sum() / 1000.0
    total_exportado_kwh = df_all['exportado_intervalo_wh'].sum() / 1000.0
    total_generacion_kwh = total_consumo_kwh + total_exportado_kwh
    
    if total_generacion_kwh > 0:
        pct_consumo = round((total_consumo_kwh / total_generacion_kwh) * 100, 1)
        pct_ared = round((total_exportado_kwh / total_generacion_kwh) * 100, 1)
    
    ganancia_cop = total_exportado_kwh * config_app.get("tarifa_cop", 850.0)
    horas_plena_carga = round(total_generacion_kwh / 5.0, 2) if total_generacion_kwh > 0 else 0.0

# --- SECCIÓN: ESTADÍSTICAS DE ENERGÍA (BARRAS + TARJETAS DE MÉTRICAS) ---
st.markdown("### Estadísticas de Energía ⚙️")

# Card superior: Generación y porcentaje dividido
st.markdown(f"""
<div class="energy-card">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
        <span style="font-size: 18px; font-weight: 600; color: #1e293b;">
            Generación: <strong style="font-size: 22px;">{total_generacion_kwh:.2f} kWh</strong>
        </span>
    </div>
    <div style="width: 100%; background-color: #3498db; border-radius: 8px; display: flex; height: 24px; overflow: hidden;">
        <div style="width: {pct_consumo}%; background-color: #8e44ad; color: white; font-weight: bold; font-size: 12px; display: flex; align-items: center; padding-left: 10px;">
            {pct_consumo}% Al consumo
        </div>
        <div style="width: {pct_ared}%; background-color: #2980b9; color: white; font-weight: bold; font-size: 12px; display: flex; align-items: center; justify-content: flex-end; padding-right: 10px;">
            {pct_ared}% A red
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# Grid de métricas en tarjetas secundarias
m1, m2, m3, m4, m5, m6 = st.columns(6)

with m1:
    st.markdown(f"""
    <div class="energy-card">
        <div class="metric-value">{total_consumo_kwh:.2f} <span style="font-size: 14px;">kWh</span></div>
        <div class="metric-label">Consumo</div>
    </div>
    """, unsafe_allow_html=True)

with m2:
    st.markdown(f"""
    <div class="energy-card">
        <div class="metric-value">{total_consumo_kwh:.2f} <span style="font-size: 14px;">kWh</span></div>
        <div class="metric-label">Importado</div>
    </div>
    """, unsafe_allow_html=True)

with m3:
    st.markdown(f"""
    <div class="energy-card">
        <div class="metric-value">{total_exportado_kwh:.2f} <span style="font-size: 14px;">kWh</span></div>
        <div class="metric-label">Energía exportada</div>
    </div>
    """, unsafe_allow_html=True)

with m4:
    st.markdown(f"""
    <div class="energy-card">
        <div class="metric-value">{total_generacion_kwh:.2f} <span style="font-size: 14px;">kWh</span></div>
        <div class="metric-label">Generación total</div>
    </div>
    """, unsafe_allow_html=True)

with m5:
    st.markdown(f"""
    <div class="energy-card">
        <div class="metric-value">${ganancia_cop:,.0f} <span style="font-size: 12px;">COP</span></div>
        <div class="metric-label">Ganancia estimada</div>
    </div>
    """, unsafe_allow_html=True)

with m6:
    st.markdown(f"""
    <div class="energy-card">
        <div class="metric-value">{horas_plena_carga:.2f} <span style="font-size: 14px;">h</span></div>
        <div class="metric-label">Horas plena carga</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# --- SECCIÓN: GRÁFICOS DINÁMICOS POR PESTAÑA (DÍA, MES, AÑO, TOTAL) ---
if not df_all.empty:
    if tab_vista == "Día":
        st.subheader("📈 Perfil de Potencia y Carga Diario (kW)")
        
        fig = go.Figure()
        df_all['potencia_kw'] = df_all['potencia_total_w'] / 1000.0
        df_all['consumo_kw'] = df_all['consumo_intervalo_wh'] / 1000.0
        df_all['export_kw'] = df_all['exportado_intervalo_wh'] / 1000.0
        
        fig.add_trace(go.Scatter(
            x=df_all['timestamp'],
            y=df_all['potencia_kw'],
            mode='lines',
            name='Producción (kW)',
            line=dict(color='#f1c40f', width=2, shape='spline'),
            fill='tozeroy',
            fillcolor='rgba(241, 196, 15, 0.1)'
        ))
        fig.add_trace(go.Scatter(
            x=df_all['timestamp'],
            y=df_all['export_kw'],
            mode='lines',
            name='Red eléctrica (Exportado kW)',
            line=dict(color='#3498db', width=2, shape='spline')
        ))
        fig.add_trace(go.Scatter(
            x=df_all['timestamp'],
            y=df_all['consumo_kw'],
            mode='lines',
            name='Carga (Consumo kW)',
            line=dict(color='#8e44ad', width=2, shape='spline')
        ))

        fig.update_layout(
            template='plotly_white',
            height=420,
            xaxis_title="Hora",
            yaxis_title="kW",
            legend=dict(orientation="h", y=1.1, x=0),
            margin=dict(l=40, r=40, t=30, b=40)
        )
        st.plotly_chart(fig, use_container_width=True)

    elif tab_vista == "Mes":
        st.subheader("📊 Consumo e Inyección Mensual por Días (kWh)")
        
        df_grouped = df_all.groupby('fecha').agg({
            'consumo_intervalo_wh': 'sum',
            'exportado_intervalo_wh': 'sum'
        }).reset_index()
        df_grouped['Consumo_kWh'] = df_grouped['consumo_intervalo_wh'] / 1000.0
        df_grouped['Exportado_kWh'] = df_grouped['exportado_intervalo_wh'] / 1000.0

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df_grouped['fecha'],
            y=df_grouped['Consumo_kWh'],
            name='Consumo (kWh)',
            marker_color='#8e44ad'
        ))
        fig.add_trace(go.Bar(
            x=df_grouped['fecha'],
            y=df_grouped['Exportado_kWh'],
            name='Exportación (kWh)',
            marker_color='#3498db'
        ))

        fig.update_layout(
            barmode='group',
            template='plotly_white',
            height=420,
            xaxis_title="Día del Mes",
            yaxis_title="kWh",
            legend=dict(orientation="h", y=1.1, x=0)
        )
        st.plotly_chart(fig, use_container_width=True)

    elif tab_vista == "Año":
        st.subheader("📊 Consumo e Inyección Anual por Meses (kWh)")
        
        df_grouped = df_all.groupby('mes').agg({
            'consumo_intervalo_wh': 'sum',
            'exportado_intervalo_wh': 'sum'
        }).reset_index()
        df_grouped['Consumo_kWh'] = df_grouped['consumo_intervalo_wh'] / 1000.0
        df_grouped['Exportado_kWh'] = df_grouped['exportado_intervalo_wh'] / 1000.0

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df_grouped['mes'],
            y=df_grouped['Consumo_kWh'],
            name='Consumo (kWh)',
            marker_color='#8e44ad'
        ))
        fig.add_trace(go.Bar(
            x=df_grouped['mes'],
            y=df_grouped['Exportado_kWh'],
            name='Exportación (kWh)',
            marker_color='#3498db'
        ))

        fig.update_layout(
            barmode='group',
            template='plotly_white',
            height=420,
            xaxis_title="Mes",
            yaxis_title="kWh",
            legend=dict(orientation="h", y=1.1, x=0)
        )
        st.plotly_chart(fig, use_container_width=True)

    else:  # Total
        st.subheader("🌐 Resumen Total Acumulado")
        
        df_grouped = df_all.groupby('anio').agg({
            'consumo_intervalo_wh': 'sum',
            'exportado_intervalo_wh': 'sum'
        }).reset_index()
        df_grouped['Consumo_kWh'] = df_grouped['consumo_intervalo_wh'] / 1000.0
        df_grouped['Exportado_kWh'] = df_grouped['exportado_intervalo_wh'] / 1000.0

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df_grouped['anio'],
            y=df_grouped['Consumo_kWh'],
            name='Consumo Total (kWh)',
            marker_color='#8e44ad'
        ))
        fig.add_trace(go.Bar(
            x=df_grouped['anio'],
            y=df_grouped['Exportado_kWh'],
            name='Exportado Total (kWh)',
            marker_color='#3498db'
        ))

        fig.update_layout(
            barmode='group',
            template='plotly_white',
            height=420,
            xaxis_title="Año",
            yaxis_title="kWh",
            legend=dict(orientation="h", y=1.1, x=0)
        )
        st.plotly_chart(fig, use_container_width=True)

    # --- DESCARGA DE DATOS POR RANGO DE FECHAS (INVITADO Y ADMIN) ---
    st.markdown("### 📥 Descargar Reporte en Excel por Rango de Fechas")
    
    fechas_disponibles = pd.to_datetime(df_all['fecha']).dt.date
    min_date = fechas_disponibles.min()
    max_date = fechas_disponibles.max()

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        fecha_inicio = st.date_input("Fecha Inicio:", value=min_date, min_value=min_date, max_value=max_date)
    with col_f2:
        fecha_fin = st.date_input("Fecha Fin:", value=max_date, min_value=min_date, max_value=max_date)

    if fecha_inicio > fecha_fin:
        st.error("⚠️ La fecha de inicio debe ser menor o igual a la fecha de fin.")
    else:
        mask = (fechas_disponibles >= fecha_inicio) & (fechas_disponibles <= fecha_fin)
        df_filtrado = df_all[mask]

        st.info(f"📊 Registros encontrados entre **{fecha_inicio}** y **{fecha_fin}**: **{len(df_filtrado)} registros**")

        if not df_filtrado.empty:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_filtrado.to_excel(writer, index=False, sheet_name='Reporte_Filtrado')
            excel_data = output.getvalue()

            st.download_button(
                label=f"📥 Descargar Excel ({fecha_inicio} a {fecha_fin})",
                data=excel_data,
                file_name=f"reporte_medidor_{fecha_inicio}_a_{fecha_fin}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary"
            )

    with st.expander("📋 Ver Tabla Completa de Registros"):
        st.dataframe(df_all, use_container_width=True)

else:
    st.info("Presiona '▶️ Iniciar Monitoreo' en la barra lateral (como Administrador) para comenzar la captura de datos.")
