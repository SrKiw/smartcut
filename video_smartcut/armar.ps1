# Borrador 480p: grano muy leve, se queda en 24 fps y corta por escenas sin volver a renderizar en Remotion.
$cortes = @(0, 4, 9, 13, 17, 21.8, 25)
$grano = "scale=480:854:flags=bicubic,noise=alls=4:allf=t,format=yuv420p"
ffmpeg -v error -y -i salida\crudo.mp4 -vf $grano -c:v libx264 -preset veryfast -crf 24 salida\SmartCut_borrador_480p.mp4
for ($i = 0; $i -lt 6; $i++) {
  $a = $cortes[$i]; $d = $cortes[$i + 1] - $a; $n = $i + 1
  ffmpeg -v error -y -ss $a -t $d -i salida\SmartCut_borrador_480p.mp4 -c:v libx264 -preset veryfast -crf 24 "salida\escena_$n.mp4"
}
$tiempos = 2.0, 3.4, 5.2, 8.0, 9.9, 11.0, 12.5, 14.0, 15.1, 16.5, 18.6, 21.4, 23.8
$lista = foreach ($t in $tiempos) { "-ss"; "$t"; "-i"; "salida\SmartCut_borrador_480p.mp4" }
$grafo = (0..($tiempos.Count - 1) | ForEach-Object { "[${_}:v]trim=end_frame=1,setpts=PTS-STARTPTS,scale=240:-2[v$_]" }) -join ";"
$unir = (0..($tiempos.Count - 1) | ForEach-Object { "[v$_]" }) -join ""
ffmpeg -v error -y @lista -filter_complex "$grafo;$unir hstack=inputs=$($tiempos.Count),scale=2600:-2[o]" -map "[o]" -frames:v 1 salida\hoja.jpg
