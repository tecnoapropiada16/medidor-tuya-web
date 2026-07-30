import streamlit as st
import tinytuya
import pandas as pd
import numpy as np
import base64
import time
from datetime import datetime
import io
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# ==================================================
# CONFIGURACIÓN TUYA CLOUD
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
    page_title="Medidor Trifásico Tuya Cloud 24/7",
    page_icon="⚡",
    layout="wide"
)

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

# Inicializar sesión
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

st.title("⚡ Medidor Trifásico - Monitor Tuya Cloud 24/7")

# Sidebar controls
st.sidebar.header("⚙️ Configuración del Monitoreo")

medidor_sel = st.sidebar.selectbox("Seleccionar Medidor:", list(MEDIDORES.keys()))
device_id = MEDIDORES[medidor_sel]

intervalo_opciones = {"5s": 5, "15s": 15, "30s": 30, "60s (1 min)": 60, "5 min": 300, "15 min": 900}
intervalo_nombre = st.sidebar.selectbox("Intervalo de Lectura:", list(intervalo_opciones.keys()), index=3)
intervalo_seg = intervalo_opciones[intervalo_nombre]

col_btn1, col_btn2 = st.sidebar.columns(2)
with col_btn1:
    if not st.session_state.monitoreo_activo:
        if st.button("▶️ Iniciar", use_container_width=True, type="primary"):
            st.session_state.monitoreo_activo = True
            st.session_state.ultimo_fetch_ts = 0
            st.rerun()
    else:
        if st.button("⏹️ Detener", use_container_width=True, type="secondary"):
            st.session_state.monitoreo_activo = False
            st.rerun()

with col_btn2:
    if st.button("🗑️ Limpiar Datos", use_container_width=True):
        st.session_state.datos_registros = []
        st.session_state.ultima_forward_wh = None
        st.session_state.ultima_reverse_wh = None
        st.session_state.contador = 0
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("📊 Estado del Servicio")
if st.session_state.monitoreo_activo:
    st.sidebar.success(f"🟢 Monitoreando cada {intervalo_seg}s")
    st_autorefresh(interval=intervalo_seg * 1000, key="tuya_autorefresh")
else:
    st.sidebar.info("⏸️ Monitoreo en pausa")

# Lógica de actualización
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

            ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            registro = {
                "timestamp": ts_str,
                "energia_consumida_wh": round(forward_wh, 4),
                "energia_inyectada_wh": round(reverse_wh, 4),
                "consumo_intervalo_wh": round(consumo_intervalo, 4),
                "exportado_intervalo_wh": round(exportado_intervalo, 4),
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

# Métricas instantáneas
st.subheader("📌 Lectura Instantánea")
if error_conexion:
    st.error(f"❌ Error de conexión: {error_conexion}")

if registro_actual:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Energía Consumida Total", f"{registro_actual['energia_consumida_wh']:.1f} Wh")
    col2.metric("Energía Inyectada Total", f"{registro_actual['energia_inyectada_wh']:.1f} Wh")
    col3.metric("Consumo Úl. Intervalo", f"{registro_actual['consumo_intervalo_wh']:.2f} Wh")
    col4.metric("Exportado Úl. Intervalo", f"{registro_actual['exportado_intervalo_wh']:.2f} Wh")

    st.markdown("#### ⚡ Medición por Fases")
    f1, f2, f3 = st.columns(3)
    with f1:
        st.markdown("**Fase A**")
        st.write(f"Voltaje: **{registro_actual['Va']} V**")
        st.write(f"Corriente: **{registro_actual['Ia']} A**")
        st.write(f"Potencia: **{registro_actual['Pa']} W**")
    with f2:
        st.markdown("**Fase B**")
        st.write(f"Voltaje: **{registro_actual['Vb']} V**")
        st.write(f"Corriente: **{registro_actual['Ib']} A**")
        st.write(f"Potencia: **{registro_actual['Pb']} W**")
    with f3:
        st.markdown("**Fase C**")
        st.write(f"Voltaje: **{registro_actual['Vc']} V**")
        st.write(f"Corriente: **{registro_actual['Ic']} A**")
        st.write(f"Potencia: **{registro_actual['Pc']} W**")

st.markdown("---")

# Gráficos y Tablas
st.subheader("📊 Historial de Consumo e Inyección por Intervalo")

if len(st.session_state.datos_registros) > 0:
    df = pd.DataFrame(st.session_state.datos_registros)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df['timestamp'],
        y=df['consumo_intervalo_wh'],
        name='Consumida (Wh)',
        marker_color='#1f77b4'
    ))
    fig.add_trace(go.Bar(
        x=df['timestamp'],
        y=df['exportado_intervalo_wh'],
        name='Exportada (Wh)',
        marker_color='#ff7f0e'
    ))
    fig.update_layout(
        barmode='group',
        title="Energía por Intervalo (Wh)",
        xaxis_title="Fecha y Hora",
        yaxis_title="Wh",
        legend_title="Tipo",
        template="plotly_white",
        height=400
    )
    st.plotly_chart(fig, use_container_width=True)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Monitoreo')
    excel_data = output.getvalue()

    st.download_button(
        label="📥 Descargar Reporte en Excel (.xlsx)",
        data=excel_data,
        file_name=f"monitoreo_tuya_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary"
    )

    st.dataframe(df, use_container_width=True)
else:
    st.info("Presiona '▶️ Iniciar' en la barra lateral para comenzar la captura de datos.")
