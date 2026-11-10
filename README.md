# SmartCut

**Le das un video largo y te devuelve clips verticales listos para publicar en TikTok, Reels y Shorts.**

SmartCut es un OpusClip hecho en casa. Corre en tu PC con Windows: el video no sale de tu computadora y a Claude solo se le manda el texto de la transcripción. Está pensado para shows, podcasts, entrevistas, radio y stand-up, con subtítulos que entienden la jerga dominicana.

Versión actual: **0.6**

---

## Qué hace

1. **Transcribe** el video con tiempos por palabra (Whisper large-v3-turbo, en tu tarjeta NVIDIA).
2. **Detecta risas y aplausos** del público.
3. **Claude elige los mejores momentos.** A cada clip le pone una puntuación de 0 a 99 (hook, flujo, valor y tendencia), además de título, hook y el texto para publicar con sus hashtags.
4. **Afina cada corte en el audio**, para no cortar palabras a la mitad. Si hay risas después del remate, el clip termina cuando acaban.
5. **Reencuadra a 9:16 siguiendo la cara de quien habla.** Si hay dos personas, cambia entre ellas según quién mueve la boca.
6. **Pone subtítulos animados y un título (hook)** arriba.
7. **Recorta los silencios** y mete un zoom leve en cada salto para que no se note.
8. **Hace una portada para cada clip.**
9. **Nombra cada video con su caption y sus hashtags**, listo para subir.

## Funciones

### Crear clips
- Acepta un link de YouTube, una ruta de tu PC o un archivo subido.
- **Fragmento:** puedes sacar clips solo de una parte del video, marcando el inicio y el fin en el reproductor. En un video de 3 horas solo se transcribe ese pedazo.
- **Qué buscas:** puedes pedir algo concreto, por ejemplo «solo los chistes sobre la familia».
- **Videos repetidos:** si ya procesaste un video, no lo vuelve a bajar ni repite los mismos momentos.
- **Gasto de Claude:** antes de llamar a Claude te dice cuánto va a costar, y después lo que costó. Puedes poner un presupuesto máximo por video.

### Subtítulos
- Estilos **Opus** (la palabra que se dice va en amarillo), **Yulian** (palabra por palabra, con las palabras clave en rojo) y **Simple**.
- Cuatro tamaños de letra: pequeño, normal, grande y gigante.
- **Quitar los signos de puntuación** (`. , ¿? ¡! …`). Deja los apóstrofes de «pa'» y «to'».
- **Corrección con Claude:** usa el glosario del cliente y la jerga dominicana, y aprende de las correcciones que haces.

### Sonido
- **Volumen parejo:** cada clip sale a −14 LUFS, el volumen de Reels y TikTok. Los videos grabados bajito se suben solos.
- **Música de fondo** que baja sola cuando hablan y sube un poco en las pausas.
- **Efectos de sonido** en los zooms, los textos animados, los lower thirds, las imágenes y, si quieres, en cada corte.

### Editor de clips (en el navegador)
- Mueves el inicio y el fin, corriges palabras y eliges las tomas: auto, recorte, completo, split o gráfico.
- **Zooms, imágenes encima y lower thirds** con nombre y cargo.
- **Textos que resaltan lo que se dice**, con 4 animaciones: *Golpe*, *Máquina de escribir*, *Marcador* y *Sello*. Eliges si van arriba, al centro o encima de los subtítulos. Un botón los pone solos en las palabras clave.
- Vista previa en vivo con los mismos subtítulos que salen en el video.
- Intro, outro y flyer al final, que se activan al descargar.
- **Descargas:** uno por uno o varios en un ZIP, con portadas y los textos para publicar.

### Editor de portadas
- Busca los mejores cuadros del clip: nítidos, bien expuestos y con la cara grande.
- Títulos con palabras resaltadas, bandas, fotos, logos y plantillas con la marca del cliente.
- **Recortar a la persona y ponerle glow o contorno**, como en las portadas de YouTube. Funciona con el fondo y con fotos sueltas.
- **Mejorar la imagen:** más contraste, nitidez y color.
- **Plantilla «YouTube: persona con glow»**: fondo oscuro, persona nítida y título gigante.
- Las portadas son verticales (9:16). También puede hacer un video con la portada al inicio.

### Clientes
Cada cliente es una carpeta dentro de `clientes/`. Puede tener:
- logo, colores, letras, intro y outro;
- tarjeta de cierre;
- glosario, fotos de las personas y su propia música.

### Usar desde otra computadora
Con **«ABRIR SmartCut en red.bat»**, SmartCut se abre en tu red de casa con usuario y clave, para usarlo desde una Mac o un teléfono.

---

## Instalar (Windows, una sola vez)

Necesitas Windows 10 u 11. Una tarjeta NVIDIA es recomendable, pero no obligatoria.

1. Baja o clona este repositorio en una carpeta fuera de OneDrive, por ejemplo `C:\SmartCut`.
2. Haz doble clic en **`INSTALAR.bat`**. Instala Python, FFmpeg y las librerías (las de la GPU si tienes NVIDIA), baja el modelo de transcripción (~1.6 GB) y crea el acceso directo. Lo que hace queda anotado en `instalacion.log`.
3. Copia `config.example.json` como **`config.json`**. Ahí cambias los valores por defecto, como cantidad de clips, duraciones y colores.
4. **Para recortar personas en las portadas**, baja el modelo MODNet (26 MB, Apache-2.0) y guárdalo como `modelos/modnet.onnx`:
   https://huggingface.co/Xenova/modnet/resolve/main/onnx/model.onnx
5. **Opcional:** pon tu API key de Claude en la app, en *Configuración*. Es pago por uso: con Sonnet son unos $0.10 por hora de video. Sin key también funciona, pero elige los clips de forma más simple.
6. **Opcional:** pon tu API key de ElevenLabs para volver a transcribir los clips con más precisión (de pago).

Las claves se guardan en `.env`, que nunca se sube al repositorio.

## Usar

| Para… | Abre… |
|---|---|
| Crear clips | `ABRIR SmartCut.bat`, o el acceso directo del escritorio |
| Editar clips y portadas | `ABRIR Editor.bat`, o el botón «Editar los clips» de la app |
| Usarlo desde la Mac o el teléfono | `ABRIR SmartCut en red.bat` (la primera vez, `PERMITIR EN LA RED (una vez).bat`) |
| Procesar sin abrir la app | Arrastra un video encima de `Arrastra un video aqui.bat` |
| Revisar si algo falla | `Diagnostico.bat` |

No cierres la ventana negra mientras usas SmartCut.

Los clips quedan en `resultados\<fecha>_<nombre del video>\`:
- `clips/`: los videos, con el caption como nombre;
- `portadas/`: las portadas;
- `galeria.html`: para ver todos los clips, copiar el texto y descargar;
- `clips.json`: los datos de cada clip.

**Música:** pon tus canciones (mp3) en la carpeta `musica` y elígelas en la app. Usa música que puedas publicar, por ejemplo de la Biblioteca de audio de YouTube.

## Cómo está hecho

| Archivo | Qué es |
|---|---|
| `miopusclip.py` | El motor: descarga, transcripción, elección de clips, cortes, cámara, subtítulos, sonido y render con FFmpeg (NVENC) |
| `app.py` | La app principal (Gradio), en el puerto 7860 |
| `editor.py` + `editor_web/` | El editor de clips y portadas (FastAPI + JavaScript), en el puerto 7861 |
| `portadas.py` | El generador de portadas: mejores cuadros, plantillas, recorte de persona y mejorador |
| `entrenamiento.py` | Guarda las correcciones de subtítulos para mejorar la transcripción |
| `exportar_nle.py` | Exporta a Premiere y DaVinci (OpenTimelineIO) |
| `sonidos/` | Efectos de sonido hechos con código usando [earshot](https://github.com/Leonxlnx/earshot) (MIT) |
| `video_smartcut/` | El video promocional de SmartCut, hecho en Remotion |
| `versiones/` | Copias de las versiones anteriores |

## Qué no está en el repositorio

Por privacidad o por licencias, no se suben:
- tus claves (`.env`) ni tu `config.json`;
- los videos y resultados;
- las carpetas de los clientes (logos y fotos de personas);
- tu música;
- el modelo MODNet;
- las texturas y letras con licencia del video promo.

## Lo que viene

Las ideas apartadas están en [PENDIENTES.md](PENDIENTES.md):
- sacar clips de directos;
- agentes que vigilan canales o noticias de farándula y sacan clips solos;
- emojis automáticos y traducción de subtítulos.
