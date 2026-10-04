# Despliegue gratis temporal (1–2 semanas)

## Recomendación

Para publicar lo que el repositorio ya puede ejecutar, usar:

- **Frontend:** Vercel Hobby, proyecto estático de Vite.
- **API:** Render Free, servicio web Python/FastAPI.
- **Datos de transacciones:** el acceso de solo lectura a S3 que el backend ya implementa como alternativa cuando no encuentra su SQLite local.

No se necesita crear una base de datos nueva para esta ruta. Vercel y Render ofrecen planes gratis adecuados para una demo breve, con límites y pausas descritos más abajo. El uso de Gemini y AWS es independiente de esos planes: confirmar sus cuotas y costos en las cuentas correspondientes y no añadir medios de pago si se quiere evitar cargos.

## Importante: estado actual de SQL

El backend **no usa `DATABASE_URL`, `SUPABASE_URL` ni `SUPABASE_ANON_KEY`**. El archivo `.env.example` los menciona, pero no hay integración con Postgres ni con Supabase. La única base SQL que consulta el código es `data/transactions.sqlite3`, en modo de solo lectura. Ese archivo mide aproximadamente 704 MB y `*.sqlite3` está excluido por `.gitignore`, por lo que no se publica junto al código ni llega a Render al conectar el repositorio. Si no existe allí, el backend busca transacciones directamente en los CSV de S3.

Por lo tanto, la configuración gratuita de esta guía **sí conecta el frontend con la API y permite que la API consulte los datos de transacciones mediante S3**, pero no crea ni conecta una base SQL remota. No se debe configurar Neon o Supabase esperando que el backend los use automáticamente.

Si es obligatorio que la API consulte Postgres, hace falta una tarea de código y migración de datos: implementar la conexión y consulta Postgres en `backend/app/tools/aws_data.py`, migrar la tabla `transactions` (esquema descrito en `build_transactions_sqlite.py`) y configurar `DATABASE_URL` como secreto del backend. Neon Free anuncia 1 GB por proyecto; verificar que el tamaño de la tabla importada quepa antes de empezar la migración. Supabase Free anuncia 500 MB, menos que el archivo SQLite actual. También habría que decidir dónde persistir los casos: hoy el store es memoria del proceso y se pierde cuando Render reinicia o duerme.

## 1. Preparar secretos

Reunir, sin guardarlos en Git:

- `GEMINI_API_KEY`: clave válida de Google AI Studio.
- `S3_BUCKET` y, si aplica, `S3_TRANSACTIONS_PREFIX` (por omisión `data/transactions/`).
- Credenciales AWS de solo lectura: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` y, si son temporales, `AWS_SESSION_TOKEN`. También se puede usar el proveedor de credenciales disponible para la cuenta.
- `AWS_DEFAULT_REGION` (por ejemplo, `us-east-1`).

Crear credenciales AWS limitadas a listar y leer únicamente el bucket/prefijo necesario. No usar credenciales administrativas. No colocar ninguna clave de Gemini o AWS en variables `VITE_*`: Vite las incorpora al JavaScript público. `.env` y las bases SQLite locales no deben subirse al repositorio.

## 2. Desplegar la API en Render

1. En Render, crear un **New > Web Service** y conectar el repositorio.
2. Dejar **Root Directory** vacío (raíz del repositorio) y seleccionar el runtime **Python**.
3. Seleccionar el plan **Free**.
4. Configurar:
   - **Build Command:** `pip install -r backend/requirements-api.txt`
   - **Start Command:** `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. En **Environment**, añadir:
   - `GEMINI_API_KEY` = clave de Google AI Studio
   - `GEMINI_MODEL` = `gemini-flash-latest` (o el modelo disponible para la clave)
   - `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` y opcionalmente `AWS_SESSION_TOKEN`
   - `AWS_DEFAULT_REGION`
   - `S3_BUCKET`
   - `S3_TRANSACTIONS_PREFIX` = `data/transactions/` si el prefijo del bucket coincide con el predeterminado
   - `CORS_ORIGINS` = origen exacto de Vercel, por ejemplo `https://mi-proyecto.vercel.app`; sin ruta ni `/` final. Tras crear el frontend, regresar aquí y reemplazar el ejemplo por su URL. Para admitir más de un origen, separarlos con comas.
6. Crear el servicio y esperar a que Render termine el build. Copiar la URL pública asignada, por ejemplo `https://mi-api.onrender.com`.
7. Abrir `https://mi-api.onrender.com/health`. Debe responder HTTP 200 con `{"status":"ok"}`. Esto valida que la API levantó; no valida por sí solo las credenciales S3 ni Gemini.

El servicio de Render duerme después de 15 minutos sin tráfico y el primer request puede tardar alrededor de un minuto en despertarlo. Su sistema de archivos es efímero: no guardar allí SQLite esperando que sobreviva reinicios, despliegues o pausas. Los servicios Free comparten un límite mensual de 750 horas por workspace y límites de tráfico/build; revisar el panel de uso. Una llamada inicial lenta o un error al consultar transacciones puede deberse a la activación en frío o a permisos/prefijo S3. Durante la demo, abrir `/health` unos minutos antes.

## 3. Desplegar el frontend en Vercel

1. En Vercel, importar el mismo repositorio como proyecto Vite.
2. Configurar:
   - **Root Directory:** `frontend`
   - **Build Command:** `npm run build`
   - **Output Directory:** `dist`
   - **Install Command:** dejar el detectado por Vercel (`npm install`)
3. En las variables de entorno del proyecto añadir:
   - `VITE_API_BASE_URL` = URL pública de Render, por ejemplo `https://mi-api.onrender.com`, sin `/` final.
4. Desplegar y copiar el dominio `.vercel.app` asignado.
5. Volver a Render y actualizar `CORS_ORIGINS` con ese origen exacto. Guardar y dejar que Render aplique el cambio/reinicie el servicio.
6. Volver a Vercel y crear un nuevo deployment si la variable `VITE_API_BASE_URL` se agregó después del primer build. Vite incorpora esta variable durante el build.

En desarrollo local, dejar `VITE_API_BASE_URL` vacío para conservar el proxy de Vite hacia `http://localhost:8000`. En producción, el frontend llama directamente a Render; por eso CORS debe permitir el dominio de Vercel. Los dominios temporales de previews de Vercel no están cubiertos automáticamente: agregar cada origen de preview necesario a `CORS_ORIGINS` o probar desde el dominio de producción.

## 4. Verificación de extremo a extremo

1. Abrir la URL pública de Vercel y confirmar que el indicador de API queda conectado.
2. En las herramientas de desarrollador del navegador, revisar que `GET https://mi-api.onrender.com/health` devuelve HTTP 200 y no aparece un error CORS.
3. Enviar un caso de prueba por la interfaz. El flujo necesita una clave Gemini válida.
4. Para validar una transacción, usar un ID presente en los datos del bucket y confirmar que Render puede listar/leer el prefijo configurado. Una respuesta HTTP 503 suele indicar configuración/credenciales ausentes; un HTTP 502 suele indicar un error al acceder al proveedor de datos.
5. Probar después de 15 minutos de inactividad para conocer el tiempo real de reactivación antes de presentar la demo.

## ¿Se puede desplegar todo junto?

No lo recomiendo para esta demo con los archivos y servicios actuales. El frontend está preparado para Vite y la API para FastAPI, pero no hay un contenedor de producción que sirva ambos; además, la SQLite grande está excluida de Git y el disco del servicio gratis de Render es efímero. Incluir la base en la imagen o añadir una integración Postgres implicaría cambios y una migración adicionales. Vercel + Render + el acceso S3 ya implementado es la ruta con menos cambios y menos puntos de fallo.

## Límites y enlaces oficiales

- [Vercel Hobby y precios](https://vercel.com/pricing)
- [Render: servicios gratis y sus límites](https://render.com/docs/free)
- [Neon: planes y límites gratuitos](https://neon.com/pricing)
- [Supabase: planes y límites gratuitos](https://supabase.com/pricing)
- [Variables de entorno en Vercel](https://vercel.com/docs/environment-variables)

Los planes y las cuotas de proveedores pueden cambiar. Confirmarlos al crear las cuentas; no tratar “gratis” como garantía de disponibilidad ni de cuota suficiente. Esta configuración sirve para demo, no para producción: el store de casos es solo de memoria, Render puede dormir el servicio y las llamadas a Gemini/S3 tienen límites externos.
