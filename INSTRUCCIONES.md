# Aplicación Medidor Tuya - Guía de Uso

Esta carpeta contiene únicamente los archivos estrictamente necesarios para ejecutar y llevar la aplicación a cualquier otro equipo Windows.

## Contenido de la Carpeta

1. **`Medidor_101025_7.py`**: El código fuente principal en Python con la funcionalidad unificada de monitoreo y la opción de seleccionar medidores (Nuevo Julbrainer y Viejo Aprotec).
2. **`requirements.txt`**: Lista de librerías de Python requeridas (`tinytuya`, `pandas`, `matplotlib`, `numpy`, `openpyxl`).
3. **`ejecutable/`**:
   - Contiene el archivo portable **`MedidorTuya.exe`**.

---

## Cómo Usarlo en Otro Equipo (Sin Instalar Python)

1. Copia la carpeta **`ejecutable`** (o solo el archivo `MedidorTuya.exe`) a un pendrive/USB o envíala a la otra computadora.
2. Haz doble clic en **`MedidorTuya.exe`**.
3. ¡Listo! La aplicación abrirá directamente sin necesidad de instalar Python ni librerías adicionales.

---

## Cómo Ejecutar el Código Python Directamente

Si estás en un equipo con Python instalado:

1. Abre la terminal en esta carpeta.
2. Instala las librerías necesarias:
   ```bash
   pip install -r requirements.txt
   ```
3. Ejecuta la aplicación:
   ```bash
   python Medidor_101025_7.py
   ```
