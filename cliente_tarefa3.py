import http.client
from http.client import HTTPException
import json
import time
import csv


# --------------------------------------------------------------- #
#           Configurações Globais (Atualizadas p/ Entrega 2)
# --------------------------------------------------------------- #

config = {
    "print_logs": True,
    "fator_de_seguranca": 0.92,                         # Atualizado conforme feedback (0.92 para priorizar 720p/1080p)
    "janela_da_media": 3,
    "num_segmentos": 20,
    
    # NOVOS LIMITES DE BUFFER DA ENTREGA 2
    "buffer_max_s": 30.0,                               # Teto absoluto do buffer
    "buffer_target_s": 15.0,                            # Nível desejado (onde o sleep começa a atuar)
    "buffer_min_s": 4.0,                                # Abaixo disso, entra em modo de emergência
    
    "url_inicial": "137.131.178.229:8080",
    "alpha_ewma": 0.125
}

def print_log(msg:str):
    if config["print_logs"]:
        print(msg)


# --------------------------------------------------------------- #
#           GET do Manifesto
# --------------------------------------------------------------- #

conexao = http.client.HTTPConnection(config["url_inicial"])
conexao.request("GET", "/manifest")
resposta = conexao.getresponse()
manifesto: dict[str] = json.loads(resposta.read())

print_log(json.dumps(manifesto, indent=3))

with open("manifesto.json", "w", encoding="utf-8") as arquivo:
    json.dump(manifesto, arquivo, indent=3)

representacoes = sorted(manifesto["representations"], key=lambda r: r["bitrate_kbps"])


# --------------------------------------------------------------- #
#               Funções de Inteligência ABR
# --------------------------------------------------------------- #

def calcular_tendencia(vazoes: list) -> float:
    n = len(vazoes)
    if n < 2:
        return 0.0
    x = list(range(1, n + 1))
    sum_x, sum_y = sum(x), sum(vazoes)
    sum_xy = sum(i * j for i, j in zip(x, vazoes))
    sum_x_quad = sum(i**2 for i in x)
    
    denominador = (n * sum_x_quad) - (sum_x ** 2)
    if denominador == 0: return 0.0
    return ((n * sum_xy) - (sum_x * sum_y)) / denominador


def escolher_qualidade(vazao_medida: float, buffer_atual: float, tendencia: float, jitter_suavizado: float) -> tuple[str, int]:
    global qualidades, bitrates

    qualidade_escolhida = qualidades[0]
    rate_escolhido = bitrates[0]
    
    # 1. Cálculo base de Throughput exigido pelo professor
    available = vazao_medida * config["fator_de_seguranca"]

    # 2. Heurística Híbrida (Buffer + Tendência + Jitter)
    # Se o tanque estiver na meta ou acima, somos otimistas (Bônus de 10%)
    if buffer_atual >= config["buffer_target_s"]:
        available *= 1.10
    # Se estiver quase zerando, modo de segurança máximo (Corte de 30%)
    elif buffer_atual <= config["buffer_min_s"]:
        available *= 0.70 

    # Punição por tendência de queda brusca
    if tendencia < -100.0: available *= 0.80
    elif tendencia < -10.0: available *= 0.90
        
    # Punição explícita por atraso caótico (Jitter EWMA Alto)
    if jitter_suavizado > 100.0: available *= 0.75

    # Logs de depuração exigidos para comprovar a seleção
    print_log(f"\tThroughput médio: {vazao_medida:.0f} kbps")
    print_log(f"\tDisponível (com Híbrida): {available:.0f} kbps")

    for rate, quality in qualities_rates.items():
        if available >= rate:
            qualidade_escolhida, rate_escolhido = quality, rate

    print_log(f"\tQualidade selecionada: {qualidade_escolhida} ({rate_escolhido} kbps)")
    return (qualidade_escolhida, rate_escolhido)


# --------------------------------------------------------------- #
#           Inicialização e Estado
# --------------------------------------------------------------- #

qualities_rates: dict[int, str] = {}
for rep in representacoes:
    qualities_rates[rep["bitrate_kbps"]] = rep["quality"]

bitrates = list(qualities_rates.keys())
qualidades = list(qualities_rates.values())

servidores = [s for s in sorted(manifesto["servers"], key=lambda server: server["priority"])]
for servidor in servidores:
    servidor["url"] = servidor["url"].split("://")[1] 
    servidor.pop("bandwidth_kbps")
    servidor.pop("jitter_ms")

print_log(f"Servidores disponíveis: {servidores}\n")

# Variáveis de Estado
vazao_media = 1000.0                # Chute inicial conservador
buffer = 0.0                        
rebuffer_acumulado = 0.0            
failover_total = 0                  
index_servidor = 0                  
ultimas_vazoes = []                 
jitter_ewma = 0.0                   
tendencia_rede = 0.0                
segundos_por_segmento = float(manifesto["segment_duration_s"])

logs_csv = {
    "segment": [], "timestamp": [], "server_id": [], "quality": [],
    "bitrate_kbps": [], "vazao_kbps": [], "download_time_s": [],
    "jitter_network_ms": [], "jitter_ewma_ms": [], "buffer_level_s": [],
    "buffer_can_play": [], "rebuffer_event": [], "stall_duration_s": [],
    "failover_total": [],
}


# --------------------------------------------------------------- #
#           Loop Principal do ABR
# --------------------------------------------------------------- #

SIMULAR_FALHA = True
SEGMENTO_FALHA = 10
falha_ja_ocorreu = False

def baixar_segmento(qualidade):
    global conexao, segmento, index_servidor, falha_ja_ocorreu

    if SIMULAR_FALHA and segmento == SEGMENTO_FALHA and index_servidor == 0 and not falha_ja_ocorreu:
        falha_ja_ocorreu = True
        raise OSError("Servidor A indisponível (SIMULAÇÃO)")

    conexao.request("GET", f"/segment/{qualidade}")
    response = conexao.getresponse()

    inicio = time.perf_counter()
    chunk_size = 8192
    dados = bytearray()
    tempos_chunks = []
    
    ultimo_tempo = time.perf_counter()
    while True:
        chunk = response.read(chunk_size)
        if not chunk: break
        agora = time.perf_counter()
        tempos_chunks.append(agora - ultimo_tempo)
        ultimo_tempo = agora
        dados.extend(chunk)
        
    tempo_download = time.perf_counter() - inicio

    jitter_ms = 0.0
    if len(tempos_chunks) > 1:
        diferencas = [abs(tempos_chunks[i] - tempos_chunks[i-1]) for i in range(1, len(tempos_chunks))]
        jitter_ms = (sum(diferencas) / len(diferencas)) * 1000.0

    return bytes(dados), tempo_download, jitter_ms


segmentos = range(1, config["num_segmentos"]+1)
n_servidores = len(servidores)

for segmento in segmentos:
    print_log(f"\n>> Segmento {segmento}")

    for tentativa in range(n_servidores):
        try:
            # Saúde da conexão
            conexao_health = http.client.HTTPConnection(servidores[tentativa]["url"])
            conexao_health.request("GET", "/health")
            health = json.loads(conexao_health.getresponse().read())
            conexao_health.close()

            if health["status"] != "ok":
                print(f"\tServidor prio {tentativa} inacessível.")
                raise HTTPException
                
            elif index_servidor > tentativa:
                conexao.close()
                conexao = http.client.HTTPConnection(servidores[tentativa]["url"])
                index_servidor = tentativa

            # Tomada de decisão
            qualidade, bitrate_escolhida = escolher_qualidade(vazao_media, buffer, tendencia_rede, jitter_ewma)
            
            # Download
            dados, tempo_download, jitter_rede = baixar_segmento(qualidade)
            vazao_atual = (8 * len(dados) / tempo_download) / 1000
            
            # Atualização do modelo preditivo (Média Janela = 3)
            ultimas_vazoes.append(vazao_atual)
            if len(ultimas_vazoes) > config["janela_da_media"]: ultimas_vazoes.pop(0)
            vazao_media = sum(ultimas_vazoes) / len(ultimas_vazoes)

            # --- ATUALIZAÇÃO DO BUFFER E SIMULAÇÃO DE PLAYBACK (ENTREGA 2) ---
            tempo_rebuffer = 0.0
            buffer_can_play = True
            
            # 1. Player consumiu vídeo DURANTE o tempo de download
            if tempo_download > buffer:
                tempo_rebuffer = tempo_download - buffer
                buffer = 0.0
                rebuffer_acumulado += tempo_rebuffer
                buffer_can_play = False
                print_log(f"\t<!> REBUFFERING: Travou por {tempo_rebuffer:.2f}s")
            else:
                buffer -= tempo_download

            # 2. Novo segmento chegou e foi adicionado
            buffer += segundos_por_segmento

            # 3. Pacing (time.sleep): Simula o limite físico do player.
            # Se já atingimos o alvo de 15s, ativamos o sleep para estabilizar e não baixar desenfreadamente.
            if buffer >= config["buffer_target_s"]:
                wait = max(0.0, segundos_por_segmento - tempo_download)
                if wait > 0:
                    print_log(f"\t[Pacing] Pausa de {wait:.2f}s para simular playback (Buffer Alvo Atingido)")
                    time.sleep(wait)
                    buffer -= wait
                    buffer = max(0.0, buffer)

            # 4. Teto absoluto de segurança
            buffer = min(config["buffer_max_s"], buffer)
            # -----------------------------------------------------------------

            # Processamento Estatístico
            if segmento == 1:
                jitter_ewma = jitter_rede
            else:
                alpha = config["alpha_ewma"]
                jitter_ewma = (alpha * jitter_rede) + ((1.0 - alpha) * jitter_ewma)
            tendencia_rede = calcular_tendencia(ultimas_vazoes)

            print_log(f"\tBuffer atual: {buffer:.2f}s | Rebuffer total: {rebuffer_acumulado:.2f}s")

            # Logs p/ CSV
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            logs_csv["segment"].append(segmento)
            logs_csv["timestamp"].append(timestamp)
            logs_csv["server_id"].append(servidores[index_servidor]["id"])
            logs_csv["quality"].append(qualidade)
            logs_csv["bitrate_kbps"].append(bitrate_escolhida)
            logs_csv["vazao_kbps"].append(round(vazao_atual, 2))
            logs_csv["download_time_s"].append(round(tempo_download, 4))
            logs_csv["jitter_network_ms"].append(round(jitter_rede, 4))
            logs_csv["jitter_ewma_ms"].append(round(jitter_ewma, 4))
            logs_csv["buffer_level_s"].append(round(buffer, 2))
            logs_csv["buffer_can_play"].append(int(buffer_can_play))
            logs_csv["rebuffer_event"].append(1 if not buffer_can_play else 0)
            logs_csv["stall_duration_s"].append(round(tempo_rebuffer, 2))
            logs_csv["failover_total"].append(failover_total)

            break

        except (HTTPException, OSError) as e:
            failover_total += 1
            if tentativa < n_servidores - 1:
                print_log("\tTentativa falhou. Failover para o próximo servidor...")
                conexao.close()
                conexao = http.client.HTTPConnection(servidores[tentativa+1]["url"])
                index_servidor = tentativa+1
            else:
                raise RuntimeError("<!> Sem servidores disponíveis. Encerrando.")

conexao.close()

# --------------------------------------------------------------- #
#           Métricas CSV
# --------------------------------------------------------------- #

csv_file = open("metricas_tarefa3.csv", "w", newline="", encoding="utf-8")
writer = csv.writer(csv_file)
writer.writerow(list(logs_csv.keys()))
for i in segmentos:
    linha = [coluna[i-1] for coluna in logs_csv.values()]
    writer.writerow(linha)
csv_file.close()