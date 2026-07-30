import streamlit as st
import tinytuya
import pandas as pd
import numpy as np
import base64
import time
import os
import json
import threading
from datetime import datetime, date, timezone, timedelta
import io
import plotly.graph_objects as go
import plotly.express as px
from streamlit_autorefresh import st_autorefresh

# ==================================================
# CONFIGURACIÓN ZONA HORARIA COLOMBIA (UTC-5)
# ==================================================
COLOMBIA_TZ = timezone(timedelta(hours=-5))

def get_colombia_now():
    return datetime.now(COLOMBIA_TZ)

# ==================================================
# CONFIGURACIÓN TUYA CLOUD & INTERVALO FIJO (1 MIN)
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
INTERVALO_SEG = 60  # Monitoreo continuo fijo a 1 minuto (60 segundos)

CONFIG_FILE = "config_persistent.json"
DATA_FILE = "datos_monitoreo.json"

st.set_page_config(
    page_title="Datos Operativos - Medidor Tuya Cloud 24/7 (Colombia)",
    page_icon="⚡",
    layout="wide"
)

# Estilos CSS personalizados para Dashboard Industrial
st.markdown("""
<style>
    .main-header {
        font-size: 26px;
        font-weight: 700;
        color: #1e293b;
        margin-bottom: 5px;
    }
    .status-online {
        background-color: #dcfce7;
        color: #166534;
        border: 1px solid #86efac;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 13px;
        font-weight: 700;
        display: inline-block;
    }
    .status-offline {
        background-color: #fee2e2;
        color: #991b1b;
        border: 1px solid #fca5a5;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 13px;
        font-weight: 700;
        display: inline-block;
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
    .chart-selector-container {
        background-color: #f8fafc;
        padding: 10px 16px;
        border-radius: 10px;
        border: 1px solid #e2e8f0;
        margin-bottom: 15px;
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

# FUNCIONES DE PERSISTENCIA EN DISCO (JSON Y NUBE)
def cargar_config_persistente():
    default_config = {
        "admin_password": "admin",
        "monitoreo_activo": False,
        "medidor_sel": "Medidor Nuevo (Julbrainer)",
        "tarifa_cop": 850.0,
        "is_online": False,
        "last_online_check": "Sin lecturas recientes"
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

# HILO DE MONITOREO DE FONDO 24/7 (Monitoreo continuo fijo cada 1 minuto)
if "thread_started" not in globals():
    globals()["thread_started"] = False

def background_tuya_worker():
    print("[HILO FONDO] Servicio de monitoreo 24/7 iniciado (Intervalo continuo: 1 minuto)...")
    while True:
        try:
            cfg = cargar_config_persistente()
            if cfg.get("monitoreo_activo", False):
                medidor_nombre = cfg.get("medidor_sel", "Medidor Nuevo (Julbrainer)")
                device_id = MEDIDORES.get(medidor_nombre, list(MEDIDORES.values())[0])

                cloud = tinytuya.Cloud(
                    apiRegion=CONFIG["API_REGION"],
                    apiKey=CONFIG["API_KEY"],
                    apiSecret=CONFIG["API_SECRET"],
                    apiDeviceID=device_id
                )
                raw = cloud.getstatus(device_id)
                ahora_dt = get_colombia_now()
                ts_str = ahora_dt.strftime("%Y-%m-%d %H:%M:%S")

                if raw and raw.get("success", False):
                    cfg["is_online"] = True
                    cfg["last_online_check"] = ts_str
                    guardar_config_persistente(cfg)

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

                    total_power = phase_values.get("PA", 0.0) + phase_values.get("PB", 0.0) + phase_values.get("PC", 0.0)

                    nuevo_registro = {
                        "timestamp": ts_str,
                        "fecha": ahora_dt.strftime("%Y-%m-%d"),
                        "hora": ahora_dt.strftime("%H:%M:%S"),
                        "hora_slot": ahora_dt.strftime("%H:00"),
                        "fecha_hora_slot": ahora_dt.strftime("%Y-%m-%d %H:00"),
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
                    print(f"[HILO FONDO] Registro guardado (Intervalo 1 min) #{len(datos_existentes)}: {ts_str}")
                else:
                    cfg["is_online"] = False
                    cfg["last_online_check"] = ts_str
                    guardar_config_persistente(cfg)

                time.sleep(INTERVALO_SEG)
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

# Inicializar estado de administrador en sesión
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

# --- SIDEBAR (ACCESO, ROLES Y CONTROLES ADMIN) ---
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

st.sidebar.caption("⏱️ Frecuencia de Lectura: **Monitoreo Continuo (1 minuto)**")

if st.session_state.is_admin:
    nueva_tarifa = st.sidebar.number_input(
        "Tarifa COP/kWh:",
        value=float(config_app.get("tarifa_cop", 850.0)),
        step=50.0
    )
    if nueva_tarifa != config_app.get("tarifa_cop"):
        config_app["tarifa_cop"] = nueva_tarifa
        guardar_config_persistente(config_app)

st.sidebar.markdown("---")

# Botones de inicio y detención
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

if config_app.get("monitoreo_activo", False):
    st.sidebar.success("🟢 Monitoreo Continuo 24/7 Activo (Cada 1 min)")
    st_autorefresh(interval=INTERVALO_SEG * 1000, key="tuya_autorefresh")
else:
    st.sidebar.info("⏸️ Monitoreo Pausado")

# --- CARGA DE DATOS DESDE DISCO ---
raw_records = cargar_datos_persistentes()
df_all = pd.DataFrame(raw_records) if len(raw_records) > 0 else pd.DataFrame()

if not df_all.empty:
    if "hora_slot" not in df_all.columns:
        df_all["hora_slot"] = pd.to_datetime(df_all["timestamp"]).dt.strftime("%H:00")
    if "fecha_hora_slot" not in df_all.columns:
        df_all["fecha_hora_slot"] = pd.to_datetime(df_all["timestamp"]).dt.strftime("%Y-%m-%d %H:00")

# --- ENCABEZADO Y ESTADO DEL MEDIDOR EN LÍNEA ---
col_head1, col_head2 = st.columns([3, 2])

with col_head1:
    st.markdown("<div class='main-header'>⚡ Datos Operativos - Medidor Tuya Cloud</div>", unsafe_allow_html=True)
    st.caption(f"🕒 Hora Actual Colombia (UTC-5): **{get_colombia_now().strftime('%Y-%m-%d %H:%M:%S')}**")

with col_head2:
    st.markdown("<div style='text-align: right; margin-top: 5px;'>", unsafe_allow_html=True)
    if config_app.get("is_online", False):
        st.markdown(f"<span class='status-online'>🟢 MEDIDOR EN LÍNEA</span>", unsafe_allow_html=True)
        st.caption(f"Última verificación: {config_app.get('last_online_check', '')}")
    else:
        st.markdown(f"<span class='status-offline'>🔴 MEDIDOR DESCONECTADO / OFFLINE</span>", unsafe_allow_html=True)
        st.caption(f"Última lectura: {config_app.get('last_online_check', 'Sin conexión')}")
    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("---")

# Variables para las métricas globales
total_consumo_kwh = 0.0
total_exportado_kwh = 0.0
total_generacion_kwh = 0.0
pct_consumo = 100.0
pct_ared = 0.0
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

# --- SECCIÓN: ESTADÍSTICAS DE ENERGÍA ---
st.markdown("### Estadísticas de Energía ⚙️")

st.markdown(f"""
<div class="energy-card">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
        <span style="font-size: 18px; font-weight: 600; color: #1e293b;">
            Consumo Total Medido: <strong style="font-size: 22px;">{total_consumo_kwh:.2f} kWh</strong>
        </span>
    </div>
    <div style="width: 100%; background-color: #e2e8f0; border-radius: 8px; display: flex; height: 24px; overflow: hidden;">
        <div style="width: {pct_consumo}%; background-color: #8e44ad; color: white; font-weight: bold; font-size: 12px; display: flex; align-items: center; padding-left: 10px;">
            {pct_consumo}% Al consumo
        </div>
        <div style="width: {pct_ared}%; background-color: #2980b9; color: white; font-weight: bold; font-size: 12px; display: flex; align-items: center; justify-content: flex-end; padding-right: 10px;">
            {pct_ared}% A red (Inyección)
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

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
        <div class="metric-label">Importado (Red)</div>
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
        <div class="metric-label">Energía Total</div>
    </div>
    """, unsafe_allow_html=True)

with m5:
    st.markdown(f"""
    <div class="energy-card">
        <div class="metric-value">${ganancia_cop:,.0f} <span style="font-size: 12px;">COP</span></div>
        <div class="metric-label">Ganancia inyección</div>
    </div>
    """, unsafe_allow_html=True)

with m6:
    st.markdown(f"""
    <div class="energy-card">
        <div class="metric-value">{horas_plena_carga:.2f} <span style="font-size: 14px;">h</span></div>
        <div class="metric-label">Horas equivalente</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# --- SECCIÓN: MONITOREO DINÁMICO DE FASES (VOLTAJE Y AMPERAJE) ---
st.markdown("### 🎛️ Monitoreo de Fases en Tiempo Real (Voltaje y Amperaje)")

latest_va = df_all.iloc[-1]['Va'] if not df_all.empty and 'Va' in df_all.columns else 0.0
latest_vb = df_all.iloc[-1]['Vb'] if not df_all.empty and 'Vb' in df_all.columns else 0.0
latest_vc = df_all.iloc[-1]['Vc'] if not df_all.empty and 'Vc' in df_all.columns else 0.0

latest_ia = df_all.iloc[-1]['Ia'] if not df_all.empty and 'Ia' in df_all.columns else 0.0
latest_ib = df_all.iloc[-1]['Ib'] if not df_all.empty and 'Ib' in df_all.columns else 0.0
latest_ic = df_all.iloc[-1]['Ic'] if not df_all.empty and 'Ic' in df_all.columns else 0.0

col_g_v1, col_g_v2, col_g_v3 = st.columns(3)

def crear_gauge_voltaje(valor, titulo, color="#2563eb"):
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=valor,
        number={'suffix': " V", 'font': {'size': 24, 'color': "#1e293b"}},
        title={'text': titulo, 'font': {'size': 16, 'color': "#475569"}},
        gauge={
            'axis': {'range': [0, 300], 'tickwidth': 1, 'tickcolor': "#cbd5e1"},
            'bar': {'color': color},
            'bgcolor': "white",
            'borderwidth': 2,
            'bordercolor': "#e2e8f0",
            'steps': [
                {'range': [0, 100], 'color': "#f1f5f9"},
                {'range': [100, 250], 'color': "#e2e8f0"},
                {'range': [250, 300], 'color': "#fee2e2"}
            ],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': 240
            }
        }
    ))
    fig.update_layout(height=200, margin=dict(l=20, r=20, t=30, b=10))
    return fig

with col_g_v1:
    st.plotly_chart(crear_gauge_voltaje(latest_va, "Voltaje Fase A (Va)", "#3b82f6"), use_container_width=True)

with col_g_v2:
    st.plotly_chart(crear_gauge_voltaje(latest_vb, "Voltaje Fase B (Vb)", "#8b5cf6"), use_container_width=True)

with col_g_v3:
    st.plotly_chart(crear_gauge_voltaje(latest_vc, "Voltaje Fase C (Vc)", "#ec4899"), use_container_width=True)

col_g_i1, col_g_i2, col_g_i3 = st.columns(3)

def crear_gauge_amperaje(valor, titulo, color="#059669"):
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=valor,
        number={'suffix': " A", 'font': {'size': 24, 'color': "#1e293b"}},
        title={'text': titulo, 'font': {'size': 16, 'color': "#475569"}},
        gauge={
            'axis': {'range': [0, 80], 'tickwidth': 1, 'tickcolor': "#cbd5e1"},
            'bar': {'color': color},
            'bgcolor': "white",
            'borderwidth': 2,
            'bordercolor': "#e2e8f0",
            'steps': [
                {'range': [0, 30], 'color': "#ecfdf5"},
                {'range': [30, 60], 'color': "#d1fae5"},
                {'range': [60, 80], 'color': "#fef3c7"}
            ]
        }
    ))
    fig.update_layout(height=200, margin=dict(l=20, r=20, t=30, b=10))
    return fig

with col_g_i1:
    st.plotly_chart(crear_gauge_amperaje(latest_ia, "Corriente Fase A (Ia)", "#10b981"), use_container_width=True)

with col_g_i2:
    st.plotly_chart(crear_gauge_amperaje(latest_ib, "Corriente Fase B (Ib)", "#f59e0b"), use_container_width=True)

with col_g_i3:
    st.plotly_chart(crear_gauge_amperaje(latest_ic, "Corriente Fase C (Ic)", "#6366f1"), use_container_width=True)

if not df_all.empty:
    with st.expander("📈 Ver Evolución Histórica de Amperajes y Voltajes por Fase", expanded=True):
        col_chart_v, col_chart_i = st.columns(2)
        
        with col_chart_v:
            fig_v = go.Figure()
            fig_v.add_trace(go.Scatter(
                x=df_all['timestamp'], y=df_all['Va'], mode='lines', name='Va (Voltios)', line=dict(color='#3b82f6'),
                hovertemplate='<b>%{x}</b><br>Va: <b>%{y:.1f} V</b><extra></extra>'
            ))
            fig_v.add_trace(go.Scatter(
                x=df_all['timestamp'], y=df_all['Vb'], mode='lines', name='Vb (Voltios)', line=dict(color='#8b5cf6'),
                hovertemplate='<b>%{x}</b><br>Vb: <b>%{y:.1f} V</b><extra></extra>'
            ))
            fig_v.add_trace(go.Scatter(
                x=df_all['timestamp'], y=df_all['Vc'], mode='lines', name='Vc (Voltios)', line=dict(color='#ec4899'),
                hovertemplate='<b>%{x}</b><br>Vc: <b>%{y:.1f} V</b><extra></extra>'
            ))
            fig_v.update_layout(title="Variación de Voltajes por Fase (V)", template='plotly_white', height=300, margin=dict(l=20, r=20, t=40, b=20), hovermode='x unified')
            st.plotly_chart(fig_v, use_container_width=True)

        with col_chart_i:
            fig_i = go.Figure()
            fig_i.add_trace(go.Scatter(
                x=df_all['timestamp'], y=df_all['Ia'], mode='lines', name='Ia (Amperios)', line=dict(color='#10b981'),
                hovertemplate='<b>%{x}</b><br>Ia: <b>%{y:.2f} A</b><extra></extra>'
            ))
            fig_i.add_trace(go.Scatter(
                x=df_all['timestamp'], y=df_all['Ib'], mode='lines', name='Ib (Amperios)', line=dict(color='#f59e0b'),
                hovertemplate='<b>%{x}</b><br>Ib: <b>%{y:.2f} A</b><extra></extra>'
            ))
            fig_i.add_trace(go.Scatter(
                x=df_all['timestamp'], y=df_all['Ic'], mode='lines', name='Ic (Amperios)', line=dict(color='#6366f1'),
                hovertemplate='<b>%{x}</b><br>Ic: <b>%{y:.2f} A</b><extra></extra>'
            ))
            fig_i.update_layout(title="Variación de Amperajes por Fase (A)", template='plotly_white', height=300, margin=dict(l=20, r=20, t=40, b=20), hovermode='x unified')
            st.plotly_chart(fig_i, use_container_width=True)

st.markdown("---")

# =========================================================================
# SECCIÓN: GRÁFICOS DINÁMICOS CON SELECCIÓN TEMPORAL DIRECTAMENTE SOBRE EL GRÁFICO
# =========================================================================
st.markdown("### 📊 Histórico de Consumo y Carga Electrica")

# SELECCIÓN DE VISTA TEMPORAL COLOCADA DIRECTAMENTE SOBRE EL GRÁFICO
st.markdown("<div class='chart-selector-container'>", unsafe_allow_html=True)
tab_vista = st.radio(
    "Seleccionar Período de Tiempo:",
    ["Hora a Hora", "Día", "Mes", "Año", "Total"],
    horizontal=True,
    key="selected_view_mode_above_chart"
)
st.markdown("</div>", unsafe_allow_html=True)

if not df_all.empty:
    if tab_vista == "Hora a Hora":
        st.subheader("📊 Consumo Acumulado Hora a Hora (00 a 23)")
        
        fechas_unicas = sorted(df_all['fecha'].unique(), reverse=True)
        col_h1, col_h2 = st.columns([1, 3])
        with col_h1:
            fecha_sel_hora = st.selectbox("Seleccionar Fecha:", fechas_unicas, index=0)
        
        df_dia_sel = df_all[df_all['fecha'] == fecha_sel_hora].copy()
        df_dia_sel['hora_str'] = pd.to_datetime(df_dia_sel['timestamp']).dt.strftime('%H')
        
        df_grouped_h = df_dia_sel.groupby('hora_str').agg({
            'consumo_intervalo_wh': 'sum',
            'exportado_intervalo_wh': 'sum'
        }).reset_index()
        
        horas_completas = [f"{h:02d}" for h in range(24)]
        df_24h = pd.DataFrame({'hora_str': horas_completas})
        df_24h = pd.merge(df_24h, df_grouped_h, on='hora_str', how='left').fillna(0.0)
        
        df_24h['Consumo_kWh'] = df_24h['consumo_intervalo_wh'] / 1000.0
        df_24h['Exportado_kWh'] = df_24h['exportado_intervalo_wh'] / 1000.0

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df_24h['hora_str'],
            y=df_24h['Consumo_kWh'],
            name='Consumo (kWh)',
            marker_color='#5c82ff',
            marker_line_color='#3b82f6',
            marker_line_width=1,
            text=df_24h['Consumo_kWh'].apply(lambda v: f"{v:.1f}" if v > 0 else ""),
            textposition='outside',
            hovertemplate='<b>%{x}</b><br>2026   <b>%{y:.1f}</b>  (kWh)<extra></extra>'
        ))

        if df_24h['Exportado_kWh'].sum() > 0:
            fig.add_trace(go.Bar(
                x=df_24h['hora_str'],
                y=df_24h['Exportado_kWh'],
                name='Exportación (kWh)',
                marker_color='#3498db',
                text=df_24h['Exportado_kWh'].apply(lambda v: f"{v:.1f}" if v > 0 else ""),
                textposition='outside',
                hovertemplate='<b>%{x}</b><br>Exportado   <b>%{y:.1f}</b>  (kWh)<extra></extra>'
            ))

        fig.update_layout(
            barmode='group',
            template='plotly_white',
            height=430,
            xaxis=dict(
                title="Hora del Día (00, 01, 02... 23)",
                type='category',
                tickmode='array',
                tickvals=horas_completas,
                ticktext=horas_completas
            ),
            yaxis_title="kWh",
            legend=dict(orientation="h", y=1.12, x=0),
            margin=dict(l=30, r=30, t=30, b=40)
        )
        st.plotly_chart(fig, use_container_width=True)

    elif tab_vista == "Día":
        st.subheader("📊 Consumo Acumulado por Días del Mes (01 a 31)")
        
        df_all['mes_str'] = pd.to_datetime(df_all['timestamp']).dt.strftime('%Y-%m')
        meses_unicos = sorted(df_all['mes_str'].unique(), reverse=True)
        
        col_d1, col_d2 = st.columns([1, 3])
        with col_d1:
            mes_sel_dia = st.selectbox("Seleccionar Mes:", meses_unicos, index=0)
        
        df_mes_sel = df_all[df_all['mes_str'] == mes_sel_dia].copy()
        df_mes_sel['dia_str'] = pd.to_datetime(df_mes_sel['timestamp']).dt.strftime('%d')
        
        df_grouped_d = df_mes_sel.groupby('dia_str').agg({
            'consumo_intervalo_wh': 'sum',
            'exportado_intervalo_wh': 'sum'
        }).reset_index()
        
        dias_completos = [f"{d:02d}" for d in range(1, 32)]
        df_31d = pd.DataFrame({'dia_str': dias_completos})
        df_31d = pd.merge(df_31d, df_grouped_d, on='dia_str', how='left').fillna(0.0)
        
        df_31d['Consumo_kWh'] = df_31d['consumo_intervalo_wh'] / 1000.0
        df_31d['Exportado_kWh'] = df_31d['exportado_intervalo_wh'] / 1000.0
        
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df_31d['dia_str'],
            y=df_31d['Consumo_kWh'],
            name='Consumo (kWh)',
            marker_color='#5c82ff',
            marker_line_color='#3b82f6',
            marker_line_width=1,
            text=df_31d['Consumo_kWh'].apply(lambda v: f"{v:.1f}" if v > 0 else ""),
            textposition='outside',
            hovertemplate='<b>Día %{x}</b><br>2026   <b>%{y:.1f}</b>  (kWh)<extra></extra>'
        ))
        
        if df_31d['Exportado_kWh'].sum() > 0:
            fig.add_trace(go.Bar(
                x=df_31d['dia_str'],
                y=df_31d['Exportado_kWh'],
                name='Exportación (kWh)',
                marker_color='#3498db',
                text=df_31d['Exportado_kWh'].apply(lambda v: f"{v:.1f}" if v > 0 else ""),
                textposition='outside',
                hovertemplate='<b>Día %{x}</b><br>Exportado   <b>%{y:.1f}</b>  (kWh)<extra></extra>'
            ))

        fig.update_layout(
            barmode='group',
            template='plotly_white',
            height=430,
            xaxis=dict(
                title="Día del Mes (01, 02, 03... 31)",
                type='category',
                tickmode='array',
                tickvals=dias_completos,
                ticktext=dias_completos
            ),
            yaxis_title="kWh",
            legend=dict(orientation="h", y=1.12, x=0),
            margin=dict(l=30, r=30, t=30, b=40)
        )
        st.plotly_chart(fig, use_container_width=True)

        with st.expander("📈 Ver Perfil Continuo de Potencia Intradía (kW)"):
            df_all['potencia_kw'] = df_all['potencia_total_w'] / 1000.0
            fig_kw = go.Figure()
            fig_kw.add_trace(go.Scatter(
                x=df_all['timestamp'],
                y=df_all['potencia_kw'],
                mode='lines+markers',
                name='Potencia Activa Consumida (kW)',
                line=dict(color='#8e44ad', width=2, shape='spline'),
                fill='tozeroy',
                fillcolor='rgba(142, 68, 173, 0.1)',
                hovertemplate='<b>Hora:</b> %{x}<br><b>Potencia Consumida:</b> %{y:.2f} kW<extra></extra>'
            ))
            fig_kw.update_layout(template='plotly_white', height=300, xaxis_title="Hora (Colombia)", yaxis_title="kW", hovermode='x unified')
            st.plotly_chart(fig_kw, use_container_width=True)

    elif tab_vista == "Mes":
        st.subheader("📊 Consumo Acumulado por Meses del Año (01 a 12)")
        
        df_all['anio_str'] = pd.to_datetime(df_all['timestamp']).dt.strftime('%Y')
        anios_unicos = sorted(df_all['anio_str'].unique(), reverse=True)
        
        col_m1, col_m2 = st.columns([1, 3])
        with col_m1:
            anio_sel_mes = st.selectbox("Seleccionar Año:", anios_unicos, index=0)
            
        df_anio_sel = df_all[df_all['anio_str'] == anio_sel_mes].copy()
        df_anio_sel['mes_num'] = pd.to_datetime(df_anio_sel['timestamp']).dt.strftime('%m')
        
        df_grouped_m = df_anio_sel.groupby('mes_num').agg({
            'consumo_intervalo_wh': 'sum',
            'exportado_intervalo_wh': 'sum'
        }).reset_index()
        
        meses_completos = [f"{m:02d}" for m in range(1, 13)]
        df_12m = pd.DataFrame({'mes_num': meses_completos})
        df_12m = pd.merge(df_12m, df_grouped_m, on='mes_num', how='left').fillna(0.0)
        
        df_12m['Consumo_kWh'] = df_12m['consumo_intervalo_wh'] / 1000.0
        df_12m['Exportado_kWh'] = df_12m['exportado_intervalo_wh'] / 1000.0
        
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df_12m['mes_num'],
            y=df_12m['Consumo_kWh'],
            name='Consumo (kWh)',
            marker_color='#5c82ff',
            marker_line_color='#3b82f6',
            marker_line_width=1,
            text=df_12m['Consumo_kWh'].apply(lambda v: f"{v:.1f}" if v > 0 else ""),
            textposition='outside',
            hovertemplate='<b>Mes %{x}</b><br>2026   <b>%{y:.1f}</b>  (kWh)<extra></extra>'
        ))
        
        if df_12m['Exportado_kWh'].sum() > 0:
            fig.add_trace(go.Bar(
                x=df_12m['mes_num'],
                y=df_12m['Exportado_kWh'],
                name='Exportación (kWh)',
                marker_color='#3498db',
                text=df_12m['Exportado_kWh'].apply(lambda v: f"{v:.1f}" if v > 0 else ""),
                textposition='outside',
                hovertemplate='<b>Mes %{x}</b><br>Exportado   <b>%{y:.1f}</b>  (kWh)<extra></extra>'
            ))

        fig.update_layout(
            barmode='group',
            template='plotly_white',
            height=430,
            xaxis=dict(
                title="Mes del Año (01, 02, 03... 12)",
                type='category',
                tickmode='array',
                tickvals=meses_completos,
                ticktext=meses_completos
            ),
            yaxis_title="kWh",
            legend=dict(orientation="h", y=1.12, x=0),
            margin=dict(l=30, r=30, t=30, b=40)
        )
        st.plotly_chart(fig, use_container_width=True)

    else:  # Año o Total
        st.subheader("📊 Consumo Acumulado por Años (2026, 2027...)")
        
        df_all['anio_str'] = pd.to_datetime(df_all['timestamp']).dt.strftime('%Y')
        df_grouped_y = df_all.groupby('anio_str').agg({
            'consumo_intervalo_wh': 'sum',
            'exportado_intervalo_wh': 'sum'
        }).reset_index()
        
        df_grouped_y['Consumo_kWh'] = df_grouped_y['consumo_intervalo_wh'] / 1000.0
        df_grouped_y['Exportado_kWh'] = df_grouped_y['exportado_intervalo_wh'] / 1000.0

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df_grouped_y['anio_str'],
            y=df_grouped_y['Consumo_kWh'],
            name='Consumo Total (kWh)',
            marker_color='#5c82ff',
            marker_line_color='#3b82f6',
            marker_line_width=1,
            text=df_grouped_y['Consumo_kWh'].apply(lambda v: f"{v:.1f}" if v > 0 else ""),
            textposition='outside',
            hovertemplate='<b>Año %{x}</b><br>2026   <b>%{y:.1f}</b>  (kWh)<extra></extra>'
        ))
        
        if df_grouped_y['Exportado_kWh'].sum() > 0:
            fig.add_trace(go.Bar(
                x=df_grouped_y['anio_str'],
                y=df_grouped_y['Exportado_kWh'],
                name='Exportado Total (kWh)',
                marker_color='#3498db',
                text=df_grouped_y['Exportado_kWh'].apply(lambda v: f"{v:.1f}" if v > 0 else ""),
                textposition='outside',
                hovertemplate='<b>Año %{x}</b><br>Exportado   <b>%{y:.1f}</b>  (kWh)<extra></extra>'
            ))

        fig.update_layout(
            barmode='group',
            template='plotly_white',
            height=430,
            xaxis_title="Año (2026, 2027...)",
            yaxis_title="kWh",
            legend=dict(orientation="h", y=1.12, x=0),
            margin=dict(l=30, r=30, t=30, b=40)
        )
        st.plotly_chart(fig, use_container_width=True)

# --- SECCIÓN: DESCARGA DE DATOS EN EXCEL POR RANGO DE FECHAS (SIEMPRE VISIBLE) ---
st.markdown("### 📥 Descargar Reporte Completo en Excel por Rango de Fechas")
st.caption("Esta opción está disponible públicamente en todo momento (monitoreo activo o en pausa).")

if not df_all.empty:
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
    st.warning("⚠️ Aún no hay registros acumulados para descargar. Presiona '▶️ Iniciar Monitoreo' en la barra lateral para comenzar la recolección.")
