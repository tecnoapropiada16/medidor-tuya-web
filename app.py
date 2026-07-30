import streamlit as st
import tinytuya
import pandas as pd
import numpy as np
import base64
import time
from datetime import datetime, date
import io
import plotly.graph_objects as go
import plotly.express as px
from streamlit_autorefresh import st_autorefresh

# ==================================================
# CONFIGURACIÓN TUYA CLOUD & ADMIN
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

st.set_page_config(
    page_title="Datos Operativos - Medidor Tuya Cloud",
    page_icon="⚡",
    layout="wide"
)

# Estilos CSS personalizados para replicar el Dashboard Solar
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

# Session State Initialization
if "admin_password" not in st.session_state:
    st.session_state.admin_password = "admin"
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False
if "monitoreo_activo" not in st.session_state:
    st.session_state.monitoreo_activo = False
if "datos_registros" not in st.session_state:
    st.session_state.datos_registros = []
if "ultima_forward_wh" not in st.session_state:
    st.session_state.ultima_forward_wh = None
if "ultima_reverse_wh" not in st.session_state:
    st.session_state.ultima_reverse_wh = None
if "contador" not in st.session_state:
    st.session_state.contador = 0
if "ultimo_fetch_ts" not in st.session_state:
    st.session_state.ultimo_fetch_ts = 0
if "tarifa_cop" not in st.session_state:
    st.session_state.tarifa_cop = 850.0  # COP por kWh por defecto

# --- SIDEBAR (LOGIN & ADMIN CONTROLS) ---
st.sidebar.title("🔐 Acceso y Roles")

if not st.session_state.is_admin:
    st.sidebar.markdown("<span class='role-badge-guest'>👁️ Modo Invitado (Solo Lectura)</span>", unsafe_allow_html=True)
    st.sidebar.markdown("---")
    st.sidebar.subheader("Acceso Administrador")
    pass_input = st.sidebar.text_input("Contraseña:", type="password", key="pwd_input")
    if st.sidebar.button("🔓 Iniciar Sesión Admin"):
        if pass_input == st.session_state.admin_password:
            st.session_state.is_admin = True
            st.sidebar.success("¡Autenticado como Administrador!")
            st.rerun()
        else:
            st.sidebar.error("Contraseña incorrecta")
else:
    st.sidebar.markdown("<span class='role-badge-admin'>⚡ Modo Administrador Activo</span>", unsafe_allow_html=True)
    
    # Opción para cambiar contraseña
    with st.sidebar.expander("🔑 Cambiar Contraseña"):
        pwd_actual = st.text_input("Contraseña Actual", type="password", key="pwd_actual")
        pwd_nueva = st.text_input("Nueva Contraseña", type="password", key="pwd_nueva")
        pwd_confirm = st.text_input("Confirmar Nueva Contraseña", type="password", key="pwd_confirm")
        
        if st.button("💾 Guardar Nueva Contraseña"):
            if pwd_actual != st.session_state.admin_password:
                st.error("La contraseña actual es incorrecta.")
            elif not pwd_nueva:
                st.error("La nueva contraseña no puede estar vacía.")
            elif pwd_nueva != pwd_confirm:
                st.error("Las nuevas contraseñas no coinciden.")
            else:
                st.session_state.admin_password = pwd_nueva
                st.success("¡Contraseña actualizada con éxito!")

    if st.sidebar.button("🔒 Cerrar Sesión Admin"):
        st.session_state.is_admin = False
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Parámetros de Monitoreo")

medidor_sel = st.sidebar.selectbox(
    "Seleccionar Medidor:",
    list(MEDIDORES.keys()),
    disabled=not st.session_state.is_admin
)
device_id = MEDIDORES[medidor_sel]

intervalo_opciones = {"5s": 5, "15s": 15, "30s": 30, "60s (1 min)": 60, "5 min": 300, "15 min": 900}
intervalo_nombre = st.sidebar.selectbox(
    "Intervalo de Lectura:",
    list(intervalo_opciones.keys()),
    index=3,
    disabled=not st.session_state.is_admin
)
intervalo_seg = intervalo_opciones[intervalo_nombre]

if st.session_state.is_admin:
    st.session_state.tarifa_cop = st.sidebar.number_input(
        "Tarifa COP/kWh:",
        value=st.session_state.tarifa_cop,
        step=50.0
    )

col_btn1, col_btn2 = st.sidebar.columns(2)
with col_btn1:
    if not st.session_state.monitoreo_activo:
        if st.sidebar.button("▶️ Iniciar Monitoreo", use_container_width=True, type="primary", disabled=not st.session_state.is_admin):
            st.session_state.monitoreo_activo = True
            st.session_state.ultimo_fetch_ts = 0
            st.rerun()
    else:
        if st.sidebar.button("⏹️ Detener Monitoreo", use_container_width=True, type="secondary", disabled=not st.session_state.is_admin):
            st.session_state.monitoreo_activo = False
            st.rerun()

with col_btn2:
    if st.sidebar.button("🗑️ Limpiar Datos", use_container_width=True, disabled=not st.session_state.is_admin):
        st.session_state.datos_registros = []
        st.session_state.ultima_forward_wh = None
        st.session_state.ultima_reverse_wh = None
        st.session_state.contador = 0
        st.rerun()

if st.session_state.monitoreo_activo:
    st.sidebar.success(f"🟢 Activo ({intervalo_seg}s)")
    st_autorefresh(interval=intervalo_seg * 1000, key="tuya_autorefresh")
else:
    st.sidebar.info("⏸️ En pausa")

# --- LÓGICA DE MONITOREO / FETCH ---
ahora_ts = time.time()
debe_consultar = (
    st.session_state.monitoreo_activo and
    (ahora_ts - st.session_state.ultimo_fetch_ts >= (intervalo_seg - 0.5))
)

registro_actual = None
error_conexion = None

if debe_consultar or len(st.session_state.datos_registros) == 0:
    try:
        cloud = tinytuya.Cloud(
            apiRegion=CONFIG["API_REGION"],
            apiKey=CONFIG["API_KEY"],
            apiSecret=CONFIG["API_SECRET"],
            apiDeviceID=device_id
        )
        raw = cloud.getstatus(device_id)
        if raw and raw.get("success", False):
            datos = procesar_datos_crudos(raw.get("result", []))
            forward_wh = safe_float(datos.get("forward_energy_total", 0)) * FORWARD_SCALE_FACTOR
            reverse_wh = safe_float(datos.get("reverse_energy_total", 0)) * REVERSE_SCALE_FACTOR

            phase_values = {}
            for idx, code in enumerate(CONFIG["PHASE_CODES"], start=1):
                raw_phase = datos.get(code)
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

            consumo_intervalo = 0.0
            exportado_intervalo = 0.0
            if st.session_state.ultima_forward_wh is not None:
                consumo_intervalo = max(0.0, forward_wh - st.session_state.ultima_forward_wh)
            if st.session_state.ultima_reverse_wh is not None:
                exportado_intervalo = max(0.0, reverse_wh - st.session_state.ultima_reverse_wh)

            ahora_dt = datetime.now()
            ts_str = ahora_dt.strftime("%Y-%m-%d %H:%M:%S")
            
            total_power = phase_values.get("PA", 0.0) + phase_values.get("PB", 0.0) + phase_values.get("PC", 0.0)

            registro = {
                "timestamp": ts_str,
                "date_obj": ahora_dt,
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

            if debe_consultar:
                st.session_state.datos_registros.append(registro)
                st.session_state.ultima_forward_wh = forward_wh
                st.session_state.ultima_reverse_wh = reverse_wh
                st.session_state.contador += 1
                st.session_state.ultimo_fetch_ts = ahora_ts

            registro_actual = registro
        else:
            error_conexion = raw.get("msg", "Error de respuesta Tuya Cloud") if raw else "Sin respuesta"
    except Exception as e:
        error_conexion = str(e)

if not registro_actual and len(st.session_state.datos_registros) > 0:
    registro_actual = st.session_state.datos_registros[-1]

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

# --- PROCESAMIENTO Y FILTRADO DE DATOS ---
df_all = pd.DataFrame(st.session_state.datos_registros) if len(st.session_state.datos_registros) > 0 else pd.DataFrame()

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
    
    ganancia_cop = total_exportado_kwh * st.session_state.tarifa_cop
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
        
        # Gráfica de líneas suave (Spline)
        fig = go.Figure()
        
        # Potencia total (kW)
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

    # --- DESCARGA DE DATOS (DISPONIBLE PARA INVITADOS Y ADMIN) ---
    st.markdown("### 📥 Descargar Datos de Monitoreo")
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_export = df_all.drop(columns=['date_obj'], errors='ignore')
        df_export.to_excel(writer, index=False, sheet_name='DatosOperativos')
    excel_data = output.getvalue()

    st.download_button(
        label="📥 Descargar Reporte Completo en Excel (.xlsx)",
        data=excel_data,
        file_name=f"datos_operativos_medidor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary"
    )

    with st.expander("📋 Ver Tabla Completa de Registros"):
        st.dataframe(df_all, use_container_width=True)

else:
    st.info("Presiona '▶️ Iniciar Monitoreo' en la barra lateral (como Administrador) para comenzar la captura de datos.")
